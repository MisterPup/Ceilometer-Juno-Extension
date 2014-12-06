import abc
import datetime
import traceback

import mock
from oslo.utils import timeutils
from oslotest import base
from oslotest import mockpatch
import six
from stevedore import extension

from ceilometer import pipeline
from ceilometer import publisher
from ceilometer.publisher import test as test_publisher
from ceilometer import sample
from ceilometer import transformer
from ceilometer.transformer import accumulator
from ceilometer.transformer import arithmetic
from ceilometer.transformer import conversions


@six.add_metaclass(abc.ABCMeta)
class BasePipelineTestCase(base.BaseTestCase):
    def fake_tem_init(self):
        """Fake a transformerManager for pipeline.

        The faked entry point setting is below:
        update: TransformerClass
        except: TransformerClassException
        drop:   TransformerClassDrop
        """
        pass

    def fake_tem_get_ext(self, name):
        class_name_ext = {
            'update': self.TransformerClass,
            'except': self.TransformerClassException,
            'drop': self.TransformerClassDrop,
            'cache': accumulator.TransformerAccumulator,
            'aggregator': conversions.AggregatorTransformer,
            'unit_conversion': conversions.ScalingTransformer,
            'rate_of_change': conversions.RateOfChangeTransformer,
            'arithmetic': arithmetic.ArithmeticTransformer,
        }

        if name in class_name_ext:
            return extension.Extension(name, None,
                                       class_name_ext[name],
                                       None,
                                       )

        raise KeyError(name)

    def get_publisher(self, url, namespace=''):
        fake_drivers = {'test://': test_publisher.TestPublisher,
                        'new://': test_publisher.TestPublisher,
                        'except://': self.PublisherClassException}
        return fake_drivers[url](url)

    class PublisherClassException(publisher.PublisherBase):
        def publish_samples(self, ctxt, counters):
            raise Exception()

    class TransformerClass(transformer.TransformerBase):
        samples = []

        def __init__(self, append_name='_update'):
            self.__class__.samples = []
            self.append_name = append_name

        def flush(self, ctxt):
            return []

        def handle_sample(self, ctxt, counter):
            self.__class__.samples.append(counter)
            newname = getattr(counter, 'name') + self.append_name
            return sample.Sample(
                name=newname,
                type=counter.type,
                volume=counter.volume,
                unit=counter.unit,
                user_id=counter.user_id,
                project_id=counter.project_id,
                resource_id=counter.resource_id,
                timestamp=counter.timestamp,
                resource_metadata=counter.resource_metadata,
            )

    class TransformerClassDrop(transformer.TransformerBase):
        samples = []

        def __init__(self):
            self.__class__.samples = []

        def handle_sample(self, ctxt, counter):
            self.__class__.samples.append(counter)

    class TransformerClassException(object):
        def handle_sample(self, ctxt, counter):
            raise Exception()

    def setUp(self):
        super(BasePipelineTestCase, self).setUp()

        self.test_counter = sample.Sample(
            name='a',
            type=sample.TYPE_GAUGE,
            volume=1,
            unit='B',
            user_id="test_user",
            project_id="test_proj",
            resource_id="test_resource",
            timestamp=timeutils.utcnow().isoformat(),
            resource_metadata={}
        )

        self.useFixture(mockpatch.PatchObject(
            transformer.TransformerExtensionManager, "__init__",
            side_effect=self.fake_tem_init))

        self.useFixture(mockpatch.PatchObject(
            transformer.TransformerExtensionManager, "get_ext",
            side_effect=self.fake_tem_get_ext))

        self.useFixture(mockpatch.PatchObject(
            publisher, 'get_publisher', side_effect=self.get_publisher))

        self.transformer_manager = transformer.TransformerExtensionManager()

        self._setup_pipeline_cfg()

        self._reraise_exception = True
        self.useFixture(mockpatch.Patch(
            'ceilometer.pipeline.LOG.exception',
            side_effect=self._handle_reraise_exception))

    def _handle_reraise_exception(self, msg):
        if self._reraise_exception:
            raise Exception(traceback.format_exc())

    @abc.abstractmethod
    def _setup_pipeline_cfg(self):
        """Setup the appropriate form of pipeline config."""

    @abc.abstractmethod
    def _augment_pipeline_cfg(self):
        """Augment the pipeline config with an additional element."""

    @abc.abstractmethod
    def _break_pipeline_cfg(self):
        """Break the pipeline config with a malformed element."""

    @abc.abstractmethod
    def _set_pipeline_cfg(self, field, value):
        """Set a field to a value in the pipeline config."""

    @abc.abstractmethod
    def _extend_pipeline_cfg(self, field, value):
        """Extend an existing field in the pipeline config with a value."""

    @abc.abstractmethod
    def _unset_pipeline_cfg(self, field):
        """Clear an existing field in the pipeline config."""

    def _exception_create_pipelinemanager(self):
        self.assertRaises(pipeline.PipelineException,
                          pipeline.PipelineManager,
                          self.pipeline_cfg,
                          self.transformer_manager)