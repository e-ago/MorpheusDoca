# Copyright (c) 2023, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import time

import cudf

from morpheus.config import Config
from morpheus.config import PipelineModes
from morpheus.llm import LLMEngine
from morpheus.messages import ControlMessage
from morpheus.pipeline.linear_pipeline import LinearPipeline
from morpheus.stages.general.monitor_stage import MonitorStage
from morpheus.stages.input.in_memory_source_stage import InMemorySourceStage
from morpheus.stages.output.in_memory_sink_stage import InMemorySinkStage
from morpheus.stages.preprocess.deserialize_stage import DeserializeStage

from ..common.extracter_node import ExtracterNode
from ..common.llm_engine_stage import LLMEngineStage
from ..common.llm_generate_node import LLMGenerateNode
from ..common.nemo_llm_service import NeMoLLMService
from ..common.prompt_template_node import PromptTemplateNode
from ..common.simple_task_handler import SimpleTaskHandler

logger = logging.getLogger(f"morpheus.{__name__}")


def _build_engine():

    llm_service = NeMoLLMService()

    llm_clinet = llm_service.get_client(model_name="gpt-43b-002")

    engine = LLMEngine()

    engine.add_node("extracter", node=ExtracterNode())

    engine.add_node("prompts",
                    inputs=["/extracter"],
                    node=PromptTemplateNode(template="What is the capital of {{country}}?", template_format="jinja"))

    engine.add_node("completion", inputs=["/prompts"], node=LLMGenerateNode(llm_client=llm_clinet))

    engine.add_task_handler(inputs=["/extracter"], handler=SimpleTaskHandler())

    return engine


def pipeline(
    num_threads,
    pipeline_batch_size,
    model_max_batch_size,
):

    config = Config()
    config.mode = PipelineModes.OTHER

    # Below properties are specified by the command line
    config.num_threads = num_threads
    config.pipeline_batch_size = pipeline_batch_size
    config.model_max_batch_size = model_max_batch_size
    config.mode = PipelineModes.NLP
    config.edge_buffer_size = 128

    source_dfs = [
        cudf.DataFrame({
            "country": [
                "France",
                "Spain",
                "Italy",
                "Germany",
                "United Kingdom",
                "China",
                "Japan",
                "India",
                "Brazil",
                "United States",
            ]
        })
    ]

    completion_task = {"task_type": "completion", "task_dict": {"input_keys": ["country"], }}

    pipe = LinearPipeline(config)

    pipe.set_source(InMemorySourceStage(config, dataframes=source_dfs, repeat=1))

    pipe.add_stage(
        DeserializeStage(config, message_type=ControlMessage, task_type="llm_engine", task_payload=completion_task))

    pipe.add_stage(MonitorStage(config, description="Source rate", unit='questions'))

    pipe.add_stage(LLMEngineStage(config, engine=_build_engine()))

    sink = pipe.add_stage(InMemorySinkStage(config))

    pipe.add_stage(MonitorStage(config, description="Inference rate", unit="req", delayed_start=True))

    start_time = time.time()

    pipe.run()

    logger.info("Pipeline complete. Received %s responses", len(sink.get_messages()))

    return start_time
