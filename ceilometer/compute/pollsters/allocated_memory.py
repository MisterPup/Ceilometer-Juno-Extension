
import ceilometer
from ceilometer.compute import plugin
from ceilometer.compute.pollsters import util
from ceilometer.compute.virt import inspector as virt_inspector
from ceilometer.openstack.common.gettextutils import _
from ceilometer.openstack.common import log
from ceilometer import sample

LOG = log.getLogger(__name__)


class AllocatedMemoryPollster(plugin.ComputePollster):

    def get_samples(self, manager, cache, resources):
        for instance in resources:
            LOG.debug(_('Checking allocated memory for instance %s'), instance.id)
            try:
                memory_info = manager.inspector.inspect_allocated_memory(
                    instance)
                LOG.debug(_("ALLOCATED MEMORY: %(instance)s %(allocated)f"),
                          ({'instance': instance.__dict__,
                            'allocated': memory_info.allocated}))
                yield util.make_sample_from_instance(
                    instance,
                    name='memory.allocated',
                    type=sample.TYPE_GAUGE,
                    unit='MB',
                    volume=memory_info.allocated,
                )
            except virt_inspector.InstanceNotFoundException as err:
                # Instance was deleted while getting samples. Ignore it.
                LOG.debug(_('Exception while getting samples %s'), err)
            except ceilometer.NotImplementedError:
                # Selected inspector does not implement this pollster.
                LOG.debug(_('Obtaining Allocated Memory is not implemented for %s'
                            ), manager.inspector.__class__.__name__)
            except Exception as err:
                LOG.exception(_('Could not get Allocated Memory for '
                                '%(id)s: %(e)s'), {'id': instance.id,
                                                   'e': err})
