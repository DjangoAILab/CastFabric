from miair.miplay.rtsp import (
    ReceiverRtspSession,
    RtspBuffer,
    RtspMessage,
    RtspPhase,
    encode_rtsp,
)


def message(start_line, cseq, body=b"", **headers):
    values = {"CSeq": str(cseq), **headers}
    if body:
        values["Content-Type"] = "text/parameters"
    return RtspMessage(start_line, values, body)


def decoded(writes):
    parser = RtspBuffer()
    result = []
    for write in writes:
        result.extend(parser.feed(write))
    return result


def test_rtsp_codec_is_incremental_and_preserves_body():
    original = message(
        "GET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0",
        2,
        b"wfd_audio_codecs\r\n",
    )
    wire = encode_rtsp(original)
    parser = RtspBuffer()

    assert parser.feed(wire[:11]) == []
    assert parser.feed(wire[11:-3]) == []
    assert parser.feed(wire[-3:]) == [original]


def test_receiver_replays_captured_wfd_handshake_to_ready():
    session = ReceiverRtspSession(source_address="127.0.0.1")

    initial = session.process(
        message(
            "OPTIONS * RTSP/1.0",
            1,
            wfd_timer_server_port="2130706433:36524",
            Require="org.wfa.wfd1.0",
        )
    )
    initial_messages = decoded(initial.writes)
    assert [item.start_line for item in initial_messages] == [
        "RTSP/1.0 200 OK",
        "OPTIONS * RTSP/1.0",
    ]
    assert initial_messages[1].header("lib_version").startswith(
        "audio-speaker-mico-cloud"
    )

    options_ack = session.process(message("RTSP/1.0 200 OK", 1))
    assert options_ack.accepted
    assert session.phase == RtspPhase.AWAITING_CAPABILITY_QUERY

    capabilities = session.process(
        message(
            "GET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0",
            2,
            b"wfd_audio_codecs\r\nwfd_video_formats\r\n",
        )
    )
    capability_response = decoded(capabilities.writes)[0]
    assert b"wfd_audio_codecs: AAC 00000001 00" in capability_response.body
    assert b"wfd_video_formats: none" in capability_response.body

    selected = session.process(
        message(
            "SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0",
            3,
            b"wfd_audio_codecs: AAC 00000001 00\r\n"
            b"wfd_client_rtp_ports: RTP/AVP/TCP;interleaved mode=play\r\n",
        )
    )
    assert decoded(selected.writes)[0].start_line == "RTSP/1.0 200 OK"

    trigger = session.process(
        message(
            "SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0",
            4,
            b"wfd_trigger_method: SETUP\r\n",
        )
    )
    trigger_messages = decoded(trigger.writes)
    assert trigger_messages[1].start_line.startswith("SETUP ")
    assert trigger_messages[1].header("Transport") == "RTP/AVP/TCP;interleaved=0-1"

    setup_ack = session.process(
        message(
            "RTSP/1.0 200 OK",
            2,
            Session="588290182;timeout=60",
            Transport="RTP/AVP/TCP;interleaved=0-1;",
        )
    )
    play = decoded(setup_ack.writes)[0]
    assert play.start_line.startswith("PLAY ")
    assert play.header("Session") == "588290182"

    session.process(message("RTSP/1.0 200 OK", 3, Session="588290182"))
    ready = session.process(
        message(
            "TIME_OFFSET rtsp://localhost/wfd1.0 RTSP/1.0",
            5,
            TimeOffset="9633364443",
        )
    )
    assert ready.ready
    assert session.phase == RtspPhase.READY
    assert session.time_offset_us == 9_633_364_443


def test_capability_mismatch_stops_before_setup():
    session = ReceiverRtspSession(source_address="127.0.0.1")
    session.process(message("OPTIONS * RTSP/1.0", 1))
    session.process(message("RTSP/1.0 200 OK", 1))
    session.process(
        message("GET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0", 2)
    )
    result = session.process(
        message(
            "SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0",
            3,
            b"wfd_audio_codecs: LPCM 00000001 00\r\n",
        )
    )
    assert not result.accepted
    assert session.phase == RtspPhase.STOPPED

