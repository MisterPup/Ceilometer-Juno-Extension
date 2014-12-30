
import ceilometer
from ceilometer.compute import plugin
from ceilometer.compute.pollsters import util
from ceilometer.compute.virt import inspector as virt_inspector
from ceilometer.openstack.common.gettextutils import _
from ceilometer.openstack.common import log
from ceilometer import sample

LOG = log.getLogger(__name__)


class HostMemoryUsage(plugin.ComputePollster):

    def get_samples(self, manager, cache, resources):
        for host_res_id in resources: #only one host
            hostname = host_res_id.split('_')[0]
            LOG.debug(_('Checking memory usage for host %s'), host_res_id)
            try:
                memory_info = manager.inspector.inspect_host_memory_usage(host_res_id)
                LOG.debug(_("HOST MEMORY USAGE: %(hostname)s %(usage)f"),
                          ({'hostname': hostname,
                            'usage': memory_info.usage}))
                yield util.make_sample_from_instance(
                    host_res_id,
                    name='host.memory.usage',
                    type=sample.TYPE_GAUGE,
                    unit='%',
                    volume=memory_info.usage,
                )
            except ceilometer.NotImplementedError:
                # Selected inspector does not implement this pollster.
                LOG.debug(_('Obtaining Host Memory Usage is not implemented for %s'
                            ), manager.inspector.__class__.__name__)
            except Exception as err:
                LOG.exception(_('Could not get Host Memory Usage for '
                                '%(hostname)s: %(e)s'), 
                               {'hostname': hostname, 'e': err})

    @property
    def default_discovery(self):
        return 'host_resource_id'
