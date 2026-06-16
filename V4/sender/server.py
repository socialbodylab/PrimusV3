"""
server.py — Product-aware HTTP server facade for V4 unified sender.
"""

from paths import sender_product


def create_server(host, port, controller_state, cue_list=None, ui_lifecycle_enabled=False, osc_service=None):
    if sender_product() == "primus":
        from server_primus import create_server as _create_server
        return _create_server(
            host,
            port,
            controller_state,
            cue_list,
            ui_lifecycle_enabled=ui_lifecycle_enabled,
            osc_service=osc_service,
        )
    from server_radius import create_server as _create_server
    return _create_server(
        host,
        port,
        controller_state,
        ui_lifecycle_enabled=ui_lifecycle_enabled,
    )
