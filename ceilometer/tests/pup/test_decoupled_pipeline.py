import yaml

from ceilometer import pipeline
from ceilometer import sample
from ceilometer.tests.pup import pipeline_base


class TestDecoupledPipeline(pipeline_base.BasePipelineTestCase):
    def _setup_pipeline_cfg(self):
        source = {'name': 'test_source',
                  'interval': 5,
                  'counters': ['a'],
                  'resources': [],
                  'sinks': ['test_sink']}
        sink = {'name': 'test_sink',
                'transformers': [{'name': 'update', 'parameters': {}}],
                'publishers': ['test://']}
        self.pipeline_cfg = {'sources': [source], 'sinks': [sink]}

    def _augment_pipeline_cfg(self):
        self.pipeline_cfg['sources'].append({
            'name': 'second_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['second_sink']
        })
        self.pipeline_cfg['sinks'].append({
            'name': 'second_sink',
            'transformers': [{
                'name': 'update',
                'parameters':
                {
                    'append_name': '_new',
                }
            }],
            'publishers': ['new'],
        })

    def _break_pipeline_cfg(self):
        self.pipeline_cfg['sources'].append({
            'name': 'second_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['second_sink']
        })
        self.pipeline_cfg['sinks'].append({
            'name': 'second_sink',
            'transformers': [{
                'name': 'update',
                'parameters':
                {
                    'append_name': '_new',
                }
            }],
            'publishers': ['except'],
        })

    def _set_pipeline_cfg(self, field, value):
        if field in self.pipeline_cfg['sources'][0]:
            self.pipeline_cfg['sources'][0][field] = value
        else:
            self.pipeline_cfg['sinks'][0][field] = value

    def _extend_pipeline_cfg(self, field, value):
        if field in self.pipeline_cfg['sources'][0]:
            self.pipeline_cfg['sources'][0][field].extend(value)
        else:
            self.pipeline_cfg['sinks'][0][field].extend(value)

    def _unset_pipeline_cfg(self, field):
        if field in self.pipeline_cfg['sources'][0]:
            del self.pipeline_cfg['sources'][0][field]
        else:
            del self.pipeline_cfg['sinks'][0][field]

    def test_source_no_sink(self):
        del self.pipeline_cfg['sinks']
        self._exception_create_pipelinemanager()

    def test_source_dangling_sink(self):
        self.pipeline_cfg['sources'].append({
            'name': 'second_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['second_sink']
        })
        self._exception_create_pipelinemanager()

    def test_sink_no_source(self):
        del self.pipeline_cfg['sources']
        self._exception_create_pipelinemanager()

    def test_source_with_multiple_sinks(self):
        counter_cfg = ['a', 'b']
        self._set_pipeline_cfg('counters', counter_cfg)
        self.pipeline_cfg['sinks'].append({
            'name': 'second_sink',
            'transformers': [{
                'name': 'update',
                'parameters':
                {
                    'append_name': '_new',
                }
            }],
            'publishers': ['new'],
        })
        self.pipeline_cfg['sources'][0]['sinks'].append('second_sink')

        pipeline_manager = pipeline.PipelineManager(self.pipeline_cfg,
                                                    self.transformer_manager)

        for publisher in pipeline_manager.publishers(None):
            with publisher as p:
                p([self.test_counter])

        self.test_counter = sample.Sample(
            name='b',
            type=self.test_counter.type,
            volume=self.test_counter.volume,
            unit=self.test_counter.unit,
            user_id=self.test_counter.user_id,
            project_id=self.test_counter.project_id,
            resource_id=self.test_counter.resource_id,
            timestamp=self.test_counter.timestamp,
            resource_metadata=self.test_counter.resource_metadata,
        )

        for publisher in pipeline_manager.publishers(None):
            with publisher as p:
                p([self.test_counter])

        self.assertEqual(len(pipeline_manager.pipelines), 2)
        self.assertEqual(str(pipeline_manager.pipelines[0]),
                         'test_source:test_sink')
        self.assertEqual(str(pipeline_manager.pipelines[1]),
                         'test_source:second_sink')
        test_publisher = pipeline_manager.pipelines[0].publishers[0]
        new_publisher = pipeline_manager.pipelines[1].publishers[0]
        for publisher, sfx in [(test_publisher, '_update'),
                               (new_publisher, '_new')]:
            self.assertEqual(len(publisher.samples), 2)
            self.assertEqual(publisher.calls, 2)
            self.assertEqual(getattr(publisher.samples[0], "name"), 'a' + sfx)
            self.assertEqual(getattr(publisher.samples[1], "name"), 'b' + sfx)

    def test_multiple_sources_with_single_sink(self):
        self.pipeline_cfg['sources'].append({
            'name': 'second_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['test_sink']
        })

        pipeline_manager = pipeline.PipelineManager(self.pipeline_cfg,
                                                    self.transformer_manager)

        for publisher in pipeline_manager.publishers(None):
            with publisher as p:
                p([self.test_counter])

        self.test_counter = sample.Sample(
            name='b',
            type=self.test_counter.type,
            volume=self.test_counter.volume,
            unit=self.test_counter.unit,
            user_id=self.test_counter.user_id,
            project_id=self.test_counter.project_id,
            resource_id=self.test_counter.resource_id,
            timestamp=self.test_counter.timestamp,
            resource_metadata=self.test_counter.resource_metadata,
        )

        for publisher in pipeline_manager.publishers(None):
            with publisher as p:
                p([self.test_counter])

        self.assertEqual(len(pipeline_manager.pipelines), 1)
        self.assertEqual(str(pipeline_manager.pipelines[0]),
                         'test_source:second_source:test_sink')
        publisher = pipeline_manager.pipelines[0].publishers[0]

        self.assertEqual(len(publisher.samples), 2)
        self.assertEqual(publisher.calls, 2)
        self.assertEqual(getattr(publisher.samples[0], "name"), 'a_update')
        self.assertEqual(getattr(publisher.samples[1], "name"), 'b_update')

        transformed_samples = self.TransformerClass.samples
        self.assertEqual(len(transformed_samples), 2)
        self.assertEqual([getattr(s, 'name') for s in transformed_samples],
                         ['a', 'b'])
