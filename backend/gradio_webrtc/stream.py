import logging
from typing import Any, Callable, Literal, cast
from pathlib import Path
import gradio as gr
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from jinja2 import Template as JinjaTemplate

from .tracks import StreamHandlerImpl, VideoEventHandler
from .webrtc import WebRTC
from .webrtc_connection_mixin import WebRTCConnectionMixin
from .websocket import WebSocketHandler
from gradio import Blocks
from gradio.components.base import Component


logger = logging.getLogger(__name__)

curr_dir = Path(__file__).parent


class Body(BaseModel):
    sdp: str
    type: str
    webrtc_id: str


class Stream(FastAPI, WebRTCConnectionMixin):
    def __init__(
        self,
        handler: VideoEventHandler | StreamHandlerImpl,
        *,
        additional_outputs_handler: Callable | None = None,
        mode: Literal["send-receive", "receive", "send"] = "send-receive",
        modality: Literal["video", "audio", "audio-video"] = "video",
        concurrency_limit: int | None | Literal["default"] = "default",
        time_limit: float | None = None,
        rtp_params: dict[str, Any] | None = None,
        rtc_configuration: dict[str, Any] | None = None,
        additional_inputs: list[Component] | None = None,
        additional_outputs: list[Component] | None = None,
        generate_docs: bool = True,
        debug=False,
        routes=None,
        title="FastAPI",
        summary=None,
        description="",
        version="0.1.0",
        openapi_url="/openapi.json",
        openapi_tags=None,
        servers=None,
        dependencies=None,
        redirect_slashes=True,
        docs_url="/docs",
        redoc_url="/redoc",
        swagger_ui_oauth2_redirect_url="/docs/oauth2-redirect",
        swagger_ui_init_oauth=None,
        middleware=None,
        exception_handlers=None,
        on_startup=None,
        on_shutdown=None,
        lifespan=None,
        terms_of_service=None,
        contact=None,
        license_info=None,
        openapi_prefix="",
        root_path="",
        root_path_in_servers=True,
        responses=None,
        callbacks=None,
        webhooks=None,
        deprecated=None,
        include_in_schema=True,
        swagger_ui_parameters=None,
        separate_input_output_schemas=True,
        **extra,
    ):
        super().__init__(
            debug=debug,
            routes=routes,
            title=title,
            summary=summary,
            description=description,
            version=version,
            openapi_url=openapi_url,
            openapi_tags=openapi_tags,
            servers=servers,
            dependencies=dependencies,
            # default_response_class=default_response_class,  # type: ignore
            redirect_slashes=redirect_slashes,
            docs_url=docs_url,
            redoc_url=redoc_url,
            swagger_ui_oauth2_redirect_url=swagger_ui_oauth2_redirect_url,
            swagger_ui_init_oauth=swagger_ui_init_oauth,
            middleware=middleware,
            exception_handlers=exception_handlers,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            lifespan=lifespan,
            terms_of_service=terms_of_service,
            contact=contact,
            license_info=license_info,
            openapi_prefix=openapi_prefix,
            root_path=root_path,
            root_path_in_servers=root_path_in_servers,
            responses=responses,
            callbacks=callbacks,
            webhooks=webhooks,
            deprecated=deprecated,
            include_in_schema=include_in_schema,
            swagger_ui_parameters=swagger_ui_parameters,
            # generate_unique_id_function=generate_unique_id_function,  # type: ignore
            separate_input_output_schemas=separate_input_output_schemas,
            **extra,
        )
        self.mode = mode
        self.modality = modality
        self.rtp_params = rtp_params
        self.event_handler = handler
        self.concurrency_limit = (
            1 if concurrency_limit in ["default", None] else concurrency_limit
        )
        self.time_limit = time_limit
        self.additional_output_components = additional_outputs
        self.additional_input_components = additional_inputs
        self.additional_outputs_handler = additional_outputs_handler
        self.rtc_configuration = rtc_configuration
        self.router.post("/webrtc/offer")(self.offer)
        self.router.websocket("/telephone/handler")(self.telephone_handler)
        self.router.get("/telephone/docs")(self.coming_soon)
        self._ui = self.generate_default_ui()
        if generate_docs:
            gr.mount_gradio_app(self, self._ui, "/ui")
            gr.mount_gradio_app(self, self._webrtc_docs_gradio(), "/webrtc/docs")

    def _webrtc_docs_gradio(self):
        with gr.Blocks() as demo:
            template = Path(__file__).parent / "assets" / "webrtc_docs.md"
            contents = JinjaTemplate(template.read_text()).render(
                modality=self.modality,
                mode=self.mode,
                additional_inputs=bool(self.additional_input_components),
                additional_outputs=bool(self.additional_output_components),
            )
            if hasattr(gr, "Sidebar"):
                with gr.Sidebar(label="Docs", width="50%", open=False):
                    gr.Markdown(contents)
                self.ui.render()
            else:
                with gr.Tabs():
                    with gr.Tab(label="Docs"):
                        gr.Markdown(contents)
                    with gr.Tab("UI"):
                        self.ui.render()
        return demo

    def coming_soon(self):
        return HTMLResponse(
            content=(curr_dir / "assets" / "coming_soon.html").read_text(),
            status_code=200,
        )

    def generate_default_ui(
        self,
    ):
        same_components = []
        additional_input_components = self.additional_input_components or []
        additional_output_components = self.additional_output_components or []
        if additional_output_components and not self.additional_outputs_handler:
            raise ValueError(
                "additional_outputs_handler must be provided if there are additional output components."
            )
        if additional_input_components and additional_output_components:
            same_components = [
                component
                for component in additional_input_components
                if component in additional_output_components
            ]
            for component in additional_output_components:
                if component not in same_components:
                    same_components.append(component)
        if self.modality == "video" and self.mode == "receive":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {self.title if self.title != "FastAPI" else "Video Streaming"} (Powered by WebRTC ⚡️)
                </h1>
                """
                )
                with gr.Row():
                    if additional_input_components:
                        with gr.Column():
                            for component in additional_input_components:
                                component.render()
                            button = gr.Button("Start Stream", variant="primary")
                    with gr.Column():
                        output_video = WebRTC(
                            label="Video Stream",
                            rtc_configuration=self.rtc_configuration,
                            mode="receive",
                            modality="video",
                        )
                        for component in additional_output_components:
                            if component not in same_components:
                                component.render()
                output_video.stream(
                    fn=self.event_handler,
                    inputs=self.additional_input_components,
                    outputs=[output_video],
                    trigger=button.click,
                    time_limit=self.time_limit,
                    concurrency_limit=self.concurrency_limit,  # type: ignore
                )
                if additional_output_components:
                    assert self.additional_outputs_handler
                    output_video.on_additional_outputs(
                        self.additional_outputs_handler,
                        outputs=additional_output_components,
                    )
        elif self.modality == "video" and self.mode == "send-receive":
            css = """.my-group {max-width: 600px !important; max-height: 600 !important;}
                      .my-column {display: flex !important; justify-content: center !important; align-items: center !important};"""

            with gr.Blocks(css=css) as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {self.title if self.title != "FastAPI" else "Video Streaming"} (Powered by WebRTC ⚡️)
                </h1>
                """
                )
                with gr.Column(elem_classes=["my-column"]):
                    with gr.Group(elem_classes=["my-group"]):
                        image = WebRTC(
                            label="Stream",
                            rtc_configuration=self.rtc_configuration,
                            mode="send-receive",
                            modality="video",
                        )
                        for component in additional_input_components:
                            component.render()
                if additional_output_components:
                    with gr.Column():
                        for component in additional_output_components:
                            if component not in same_components:
                                component.render()

                    image.stream(
                        fn=self.event_handler,
                        inputs=[image] + additional_input_components,
                        outputs=[image],
                        time_limit=self.time_limit,
                        concurrency_limit=self.concurrency_limit,  # type: ignore
                    )
                    if additional_output_components:
                        assert self.additional_outputs_handler
                        image.on_additional_outputs(
                            self.additional_outputs_handler,
                            outputs=additional_output_components,
                        )
        elif self.modality == "audio" and self.mode == "receive":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {self.title if self.title != "FastAPI" else "Audio Streaming"} (Powered by WebRTC ⚡️)
                </h1>
                """
                )
                with gr.Row():
                    with gr.Column():
                        for component in additional_input_components:
                            component.render()
                        button = gr.Button("Start Stream", variant="primary")
                    if additional_output_components:
                        with gr.Column():
                            output_video = WebRTC(
                                label="Audio Stream",
                                rtc_configuration=self.rtc_configuration,
                                mode="receive",
                                modality="audio",
                            )
                            for component in additional_output_components:
                                if component not in same_components:
                                    component.render()
                output_video.stream(
                    fn=self.event_handler,
                    inputs=self.additional_input_components,
                    outputs=[output_video],
                    trigger=button.click,
                    time_limit=self.time_limit,
                    concurrency_limit=self.concurrency_limit,  # type: ignore
                )
                if additional_output_components:
                    assert self.additional_outputs_handler
                    output_video.on_additional_outputs(
                        self.additional_outputs_handler,
                        outputs=additional_output_components,
                    )
        elif self.modality == "audio" and self.mode == "send-receive":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {self.title if self.title != "FastAPI" else "Audio Streaming"} (Powered by WebRTC ⚡️)
                </h1>
                """
                )
                with gr.Row():
                    with gr.Column():
                        with gr.Group():
                            image = WebRTC(
                                label="Stream",
                                rtc_configuration=self.rtc_configuration,
                                mode="send-receive",
                                modality="audio",
                            )
                            for component in additional_input_components:
                                if component not in same_components:
                                    component.render()
                    if additional_output_components:
                        with gr.Column():
                            for component in additional_output_components:
                                component.render()

                    image.stream(
                        fn=self.event_handler,
                        inputs=[image] + additional_input_components,
                        outputs=[image],
                        time_limit=self.time_limit,
                        concurrency_limit=self.concurrency_limit,  # type: ignore
                    )
                    if additional_output_components:
                        assert self.additional_outputs_handler
                        image.on_additional_outputs(
                            self.additional_outputs_handler,
                            outputs=additional_output_components,
                        )
        return demo

    @property
    def ui(self) -> Blocks:
        return self._ui

    @ui.setter
    def _(self, blocks: Blocks):
        self._ui = blocks

    async def offer(self, body: Body):
        return await self.handle_offer(
            body.model_dump(), set_outputs=self.set_additional_outputs(body.webrtc_id)
        )

    async def handle_incoming_call(self, request: Request):
        from twilio.twiml.voice_response import Connect, VoiceResponse

        response = VoiceResponse()
        response.say("Connecting to the AI assistant.")
        connect = Connect()
        connect.stream(url=f"wss://{request.url.hostname}/telephone/handler")
        response.append(connect)
        response.say("The call has been disconnected.")
        return HTMLResponse(content=str(response), media_type="application/xml")

    async def telephone_handler(self, websocket: WebSocket):
        handler = cast(StreamHandlerImpl, self.event_handler.copy())
        ws = WebSocketHandler(handler)
        await ws.handle_websocket(websocket)
