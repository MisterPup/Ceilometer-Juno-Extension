#
# Copyright 2013 Red Hat, Inc
# Copyright 2013 eNovance <licensing@enovance.com>
#
# Authors: Eoghan Glynn <eglynn@redhat.com>
#          Julien Danjou <julien@danjou.info>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import abc

from ceilometerclient import client as ceiloclient
from oslo.config import cfg
from oslo.utils import netutils
import six
from stevedore import extension

from ceilometer.alarm.partition import coordination as alarm_coordination
from ceilometer.alarm import rpc as rpc_alarm
from ceilometer import coordination as coordination
from ceilometer import messaging
from ceilometer.openstack.common.gettextutils import _
from ceilometer.openstack.common import log
from ceilometer.openstack.common import service as os_service


OPTS = [
    cfg.IntOpt('evaluation_interval',
               default=60,
               help='Period of evaluation cycle, should'
                    ' be >= than configured pipeline interval for'
                    ' collection of underlying metrics.',
               deprecated_opts=[cfg.DeprecatedOpt(
                   'threshold_evaluation_interval', group='alarm')]),
]

cfg.CONF.register_opts(OPTS, group='alarm')
cfg.CONF.import_opt('notifier_rpc_topic', 'ceilometer.alarm.rpc',
                    group='alarm')
cfg.CONF.import_opt('partition_rpc_topic', 'ceilometer.alarm.rpc',
                    group='alarm')
cfg.CONF.import_opt('heartbeat', 'ceilometer.coordination',
                    group='coordination')
cfg.CONF.import_opt('http_timeout', 'ceilometer.service')
cfg.CONF.import_group('service_credentials', 'ceilometer.service')

LOG = log.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class AlarmService(object):

    EXTENSIONS_NAMESPACE = "ceilometer.alarm.evaluator"

    def _load_evaluators(self):
        self.evaluators = extension.ExtensionManager(
            namespace=self.EXTENSIONS_NAMESPACE,
            invoke_on_load=True,
            invoke_args=(rpc_alarm.RPCAlarmNotifier(),)
        )
        self.supported_evaluators = [ext.name for ext in
                                     self.evaluators.extensions]

    @property
    def _client(self):
        """Construct or reuse an authenticated API client."""
        if not self.api_client:
            auth_config = cfg.CONF.service_credentials
            creds = dict(
                os_auth_url=auth_config.os_auth_url,
                os_region_name=auth_config.os_region_name,
                os_tenant_name=auth_config.os_tenant_name,
                os_password=auth_config.os_password,
                os_username=auth_config.os_username,
                os_cacert=auth_config.os_cacert,
                os_endpoint_type=auth_config.os_endpoint_type,
                insecure=auth_config.insecure,
                timeout=cfg.CONF.http_timeout,
            )
            self.api_client = ceiloclient.get_client(2, **creds)
        return self.api_client

    def _evaluate_assigned_alarms(self):
        try:
            alarms = self._assigned_alarms()
            LOG.info(_('initiating evaluation cycle on %d alarms') %
                     len(alarms))
            for alarm in alarms:
                self._evaluate_alarm(alarm)
        except Exception:
            LOG.exception(_('alarm evaluation cycle failed'))

    def _evaluate_alarm(self, alarm):
        """Evaluate the alarms assigned to this evaluator."""
        if alarm.type not in self.supported_evaluators:
            LOG.debug(_('skipping alarm %s: type unsupported') %
                      alarm.alarm_id)
            return

        LOG.debug(_('evaluating alarm %s') % alarm.alarm_id)
        self.evaluators[alarm.type].obj.evaluate(alarm)

    @abc.abstractmethod
    def _assigned_alarms(self):
        pass


class AlarmEvaluationService(AlarmService, os_service.Service):

    PARTITIONING_GROUP_NAME = "alarm_evaluator"

    def __init__(self):
        super(AlarmEvaluationService, self).__init__()
        self._load_evaluators()
        self.api_client = None
        self.partition_coordinator = coordination.PartitionCoordinator()

    def start(self):
        super(AlarmEvaluationService, self).start()
        self.partition_coordinator.start()
        self.partition_coordinator.join_group(self.PARTITIONING_GROUP_NAME)

        # allow time for coordination if necessary
        delay_start = self.partition_coordinator.is_active()

        if self.evaluators:
            interval = cfg.CONF.alarm.evaluation_interval
            self.tg.add_timer(
                interval,
                self._evaluate_assigned_alarms,
                initial_delay=interval if delay_start else None)
        if self.partition_coordinator.is_active():
            heartbeat_interval = min(cfg.CONF.coordination.heartbeat,
                                     cfg.CONF.alarm.evaluation_interval / 4)
            self.tg.add_timer(heartbeat_interval,
                              self.partition_coordinator.heartbeat)
        # Add a dummy thread to have wait() working
        self.tg.add_timer(604800, lambda: None)

    def _assigned_alarms(self):
        all_alarms = self._client.alarms.list(q=[{'field': 'enabled',
                                                  'value': True}])
        return self.partition_coordinator.extract_my_subset(
            self.PARTITIONING_GROUP_NAME, all_alarms)


class SingletonAlarmService(AlarmService, os_service.Service):

    def __init__(self):
        super(SingletonAlarmService, self).__init__()
        self._load_evaluators()
        self.api_client = None

    def start(self):
        super(SingletonAlarmService, self).start()
        if self.evaluators:
            interval = cfg.CONF.alarm.evaluation_interval
            self.tg.add_timer(
                interval,
                self._evaluate_assigned_alarms,
                0)
        # Add a dummy thread to have wait() working
        self.tg.add_timer(604800, lambda: None)

    def _assigned_alarms(self):
        return self._client.alarms.list(q=[{'field': 'enabled',
                                            'value': True}])


class PartitionedAlarmService(AlarmService, os_service.Service):

    def __init__(self):
        super(PartitionedAlarmService, self).__init__()
        transport = messaging.get_transport()
        self.rpc_server = messaging.get_rpc_server(
            transport, cfg.CONF.alarm.partition_rpc_topic, self)

        self._load_evaluators()
        self.api_client = None
        self.partition_coordinator = alarm_coordination.PartitionCoordinator()

    def start(self):
        super(PartitionedAlarmService, self).start()
        if self.evaluators:
            eval_interval = cfg.CONF.alarm.evaluation_interval
            self.tg.add_timer(
                eval_interval / 4,
                self.partition_coordinator.report_presence,
                0)
            self.tg.add_timer(
                eval_interval / 2,
                self.partition_coordinator.check_mastership,
                eval_interval,
                *[eval_interval, self._client])
            self.tg.add_timer(
                eval_interval,
                self._evaluate_assigned_alarms,
                eval_interval)
        self.rpc_server.start()
        # Add a dummy thread to have wait() working
        self.tg.add_timer(604800, lambda: None)

    def stop(self):
        self.rpc_server.stop()
        super(PartitionedAlarmService, self).stop()

    def _assigned_alarms(self):
        return self.partition_coordinator.assigned_alarms(self._client)

    def presence(self, context, data):
        self.partition_coordinator.presence(data.get('uuid'),
                                            data.get('priority'))

    def assign(self, context, data):
        self.partition_coordinator.assign(data.get('uuid'),
                                          data.get('alarms'))

    def allocate(self, context, data):
        self.partition_coordinator.allocate(data.get('uuid'),
                                            data.get('alarms'))


class AlarmNotifierService(os_service.Service):

    EXTENSIONS_NAMESPACE = "ceilometer.alarm.notifier"

    notifiers = extension.ExtensionManager(EXTENSIONS_NAMESPACE,
                                           invoke_on_load=True)
    notifiers_schemas = notifiers.map(lambda x: x.name)

    def __init__(self):
        super(AlarmNotifierService, self).__init__()
        transport = messaging.get_transport()
        self.rpc_server = messaging.get_rpc_server(
            transport, cfg.CONF.alarm.notifier_rpc_topic, self)

    def start(self):
        super(AlarmNotifierService, self).start()
        self.rpc_server.start()
        # Add a dummy thread to have wait() working
        self.tg.add_timer(604800, lambda: None)

    def stop(self):
        self.rpc_server.stop()
        super(AlarmNotifierService, self).stop()

    def _handle_action(self, action, alarm_id, previous,
                       current, reason, reason_data):
        try:
            action = netutils.urlsplit(action)
        except Exception:
            LOG.error(
                _("Unable to parse action %(action)s for alarm %(alarm_id)s"),
                {'action': action, 'alarm_id': alarm_id})
            return

        try:
            notifier = self.notifiers[action.scheme].obj
        except KeyError:
            scheme = action.scheme
            LOG.error(
                _("Action %(scheme)s for alarm %(alarm_id)s is unknown, "
                  "cannot notify"),
                {'scheme': scheme, 'alarm_id': alarm_id})
            return

        try:
            LOG.debug(_("Notifying alarm %(id)s with action %(act)s") % (
                      {'id': alarm_id, 'act': action}))
            notifier.notify(action, alarm_id, previous,
                            current, reason, reason_data)
        except Exception:
            LOG.exception(_("Unable to notify alarm %s"), alarm_id)
            return

    def notify_alarm(self, context, data):
        """Notify that alarm has been triggered.

           :param context: Request context.
           :param data: (dict):

             - actions, the URL of the action to run; this is mapped to
               extensions automatically
             - alarm_id, the ID of the alarm that has been triggered
             - previous, the previous state of the alarm
             - current, the new state the alarm has transitioned to
             - reason, the reason the alarm changed its state
             - reason_data, a dict representation of the reason
        """
        actions = data.get('actions')
        if not actions:
            LOG.error(_("Unable to notify for an alarm with no action"))
            return

        for action in actions:
            self._handle_action(action,
                                data.get('alarm_id'),
                                data.get('previous'),
                                data.get('current'),
                                data.get('reason'),
                                data.get('reason_data'))
