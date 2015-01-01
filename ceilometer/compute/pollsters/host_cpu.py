
from oslo.utils import timeutils
import ceilometer
from ceilometer.compute import plugin
from ceilometer.compute.pollsters import util
from ceilometer.compute.virt import inspector as virt_inspector
from ceilometer.openstack.common.gettextutils import _
from ceilometer.openstack.common import log
from ceilometer import sample

LOG = log.getLogger(__name__)

class HostCPUPollster(plugin.ComputePollster):

    def get_samples(self, manager, cache, resources):
        for host_res_id in resources: #only one host
            hostname = host_res_id.split('_')[0]
            LOG.debug(_('Checking CPU statistics for host %s'), host_res_id)
            try:
                cpu_info = manager.inspector.inspect_host_cpu_time(host_res_id)
                LOG.debug(_("HOST CPUTIME USAGE: %(hostname)s %(time)d"),
                          {'hostname': hostname,
                           'time': cpu_info.time})
                cpu_num = {'cpu_number': cpu_info.number}
                yield sample.Sample(
                    name='host.cpu',
                    type=sample.TYPE_CUMULATIVE,
                    unit='ns',
                    volume=cpu_info.time,
                    user_id=None,
                    project_id=None,
                    resource_id=host_res_id,
                    timestamp=timeutils.isotime(),
                    resource_metadata=cpu_num
                )
            except ceilometer.NotImplementedError:
                # Selected inspector does not implement this pollster.
                LOG.debug(_('Obtaining Host CPU time is not implemented for %s'
                            ), manager.inspector.__class__.__name__)
            except Exception as err:
                LOG.exception(_('could not get Host CPU time for %(hostname)s: %(e)s'),
                              {'hostname': hostname, 'e': err})

    @property
    def default_discovery(self):
        return 'host_resource_id'
