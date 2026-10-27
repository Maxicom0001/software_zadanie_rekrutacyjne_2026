import asyncio
import time
import traceback
from collections import deque

from nicegui import ui, app, background_tasks

from communication_library.communication_manager import CommunicationManager, TransportType
from communication_library.tcp_transport import TcpSettings
from communication_library.frame import Frame
from communication_library import ids
from communication_library.exceptions import TransportTimeoutError, UnregisteredCallbackError
import procedures

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 3000
UI_PORT = 1131
SERVO_OPEN_POS = 0
SERVO_CLOSED_POS = 100
COMMAND_PRIORITY = ids.PriorityID.LOW
cm: CommunicationManager | None = None
telemetry = {
    'fuel_intake': 0.0,
    'oxidizer_intake': 0.0,
    'fuel_valve': 0.0,
    'oxidizer_valve': 0.0,
    'oxidizer_heater': False,
    'igniter': False,
    'parachute': False,
    'fuel_level': 0.0,
    'oxidizer_level': 0.0,
    'altitude': 0.0,
    'oxidizer_pressure': 0.0,
    'nosecone_tilt': 0.0
}

SERVO_NAMES = {0: 'fuel_intake',
               1: 'oxidizer_intake',
               2: 'fuel_valve',
               3: 'oxidizer_valve'}

RELAY_NAMES = {0: 'oxidizer_heater',
               1: 'igniter',
               2: 'parachute'}

SENSOR_NAMES = {0: 'fuel_level',
                1: 'oxidizer_level',
                2: 'altitude',
                3: 'oxidizer_pressure',
                4: 'nosecone_tilt'}

SERVO_IDS = {name: device_id for device_id, name in SERVO_NAMES.items()}
RELAY_IDS = {name: device_id for device_id, name in RELAY_NAMES.items()}

stats = {'count': 0, 'last_time': 0, 'last_alt': 0.0, 'last_alt_time': time.time(), 'speed': 0.0}
log_buffer = deque(maxlen=200)


def log_line(text: str):
    log_buffer.append(f"{time.strftime('%H:%M:%S')}  {text}")
    print(f"{time.strftime('%H:%M:%S')}  {text}")


def telemetry_update(frame: Frame):
    payload = frame.payload
    if isinstance(payload, (tuple, list)):
        payload = payload[0] if payload else None

    if frame.device_type == ids.DeviceID.SERVO:
        if payload is None:
            return
        name = SERVO_NAMES.get(frame.device_id)
        value = payload

    elif frame.device_type == ids.DeviceID.RELAY:
        name = RELAY_NAMES.get(frame.device_id)
        if name is None:
            return

        if payload is not None:
            value = (payload is True) or (payload == 1) or (payload == ids.OperationID.RELAY.value.OPEN)
        else:
            value = (frame.operation == ids.OperationID.RELAY.value.OPEN)

    elif frame.device_type == ids.DeviceID.SENSOR:
        if payload is None:
            return
        name = SENSOR_NAMES.get(frame.device_id)
        value = payload

    else:
        return

    if name is None:
        return

    if frame.device_type in (ids.DeviceID.SERVO, ids.DeviceID.RELAY):
        old_value = telemetry.get(name)
        if old_value is not None and old_value != value:
            if frame.device_type == ids.DeviceID.SERVO:
                log_line(f"Actuator: {name} set to {value:.1f}")
            else:
                log_line(f"Relay: {name} switched {'OPEN' if value else 'CLOSED'}")

    telemetry[name] = value


def handle_frame(frame: Frame, registered: bool):
    stats['count'] += 1
    stats['last_time'] = time.time()
    telemetry_update(frame)


SERVOS = [
    ('fuel_intake', 'Fuel intake'),
    ('oxidizer_intake', 'Oxidizer intake'),
    ('fuel_valve', 'Fuel main'),
    ('oxidizer_valve', 'Oxidizer main'),
]

RELAYS = [
    ('oxidizer_heater', 'Oxidizer heater'),
    ('igniter', 'Igniter'),
    ('parachute', 'Parachute'),
]

SENSORS = [
    ('fuel_level', 'Fuel level', '%'),
    ('oxidizer_level', 'Oxidizer level', '%'),
    ('altitude', 'Altitude', 'm'),
    ('oxidizer_pressure', 'Oxidizer pressure', 'bar'),
    ('nosecone_tilt', 'Nosecone tilt', '°'),
]


def format_Data(value, spec: str) -> str:
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return str(value)


def servo_frame(key: str, position) -> Frame:
    return procedures.change_servo_position(COMMAND_PRIORITY, SERVO_IDS[key], int(round(float(position))))


def relay_frame(key: str, state: str) -> Frame:
    operation = ids.OperationID.RELAY.value.OPEN if state == 'OPEN' else ids.OperationID.RELAY.value.CLOSE
    return Frame(ids.BoardID.ROCKET,
                 COMMAND_PRIORITY,
                 ids.ActionID.SERVICE,
                 ids.BoardID.SOFTWARE,
                 ids.DeviceID.RELAY,
                 RELAY_IDS[key],
                 ids.DataTypeID.NO_DATA,
                 operation,
                 ())


async def send_frames(frames: list):
    if cm is None:
        log_line('Disconnected from proxy')
        return
    if not frames:
        log_line('Nothing to send')
        return
    try:
        def send():
            for frame in frames:
                cm.push(frame)
            cm.send()

        await asyncio.to_thread(send)
        log_line(f"Command sent! ({len(frames)} frame(s))")
    except Exception:
        traceback.print_exc()
        log_line("Sending error occurred")


def prep_ui(data: dict, refresh_s: float = 0.2):
    servo_labels, relay_labels, sensor_labels = {}, {}, {}
    servo_state_labels = {}
    status_servo_labels, status_relay_labels = {}, {}
    led_elements = {}

    auto_state = {
        'pressurize_active': False,
        'last_heater_cmd_time': 0.0,
        'last_ox_close_time': 0.0,
        'last_fuel_close_time': 0.0
    }
    auto_btns = {}
    checklist_state = {
        'ox_filled': False,
        'fuel_filled': False,
        'intakes_closed': False,
        'ox_pressurized': False,
        'ignition': False,
        'parachute': False,
    }

    def row(label_text: str):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label(label_text).classes('text-gray-400')
            return ui.label('-').classes('font-mono text-lg')

    def led_row(label_text: str, key: str):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label(label_text).classes('text-gray-400')
            with ui.row().classes('items-center gap-3'):
                create_led(f'status_{key}')
                return ui.label('-').classes('font-mono text-lg min-w-[50px] text-right')

    def set_open_state(lbl, is_open: bool):
        lbl.text = 'OPEN' if is_open else 'CLOSED'
        lbl.classes(
            add='text-green-400' if is_open else 'text-red-400',
            remove='text-red-400' if is_open else 'text-green-400',
        )

    def create_led(key: str):
        led = ui.element('div').classes(
            'w-4 h-4 rounded-full transition-all duration-300 ease-in-out bg-gray-700 shrink-0'
        )
        led_elements[key] = led
        return led

    def set_led_color(key: str, color: str):
        if key not in led_elements:
            return
        led = led_elements[key]
        colors = {
            'red': 'bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.9)]',
            'yellow': 'bg-yellow-400 shadow-[0_0_10px_rgba(250,204,21,0.9)]',
            'green': 'bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.9)]',
            'blue': 'bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.9)]',
            'off': 'bg-gray-700 shadow-none',
        }
        all_classes = 'bg-red-500 bg-yellow-400 bg-green-500 bg-blue-500 bg-gray-700 shadow-[0_0_10px_rgba(239,68,68,0.9)] shadow-[0_0_10px_rgba(250,204,21,0.9)] shadow-[0_0_10px_rgba(34,197,94,0.9)] shadow-[0_0_10px_rgba(59,130,246,0.9)] shadow-none'
        led.classes(remove=all_classes, add=colors.get(color, colors['off']))

    def set_led_blink(key: str, color1: str, color2: str):
        if key not in led_elements:
            return

        cycle_time = time.time() % 1.5

        if cycle_time < 1.0:
            set_led_color(key, color1)
        else:
            set_led_color(key, color2)

    def manual_controls_card():
        async def send_servo(key: str, position):
            await send_frames([servo_frame(key, position)])

        async def send_relay(key: str, state: str, label):
            label.text = state
            await send_frames([relay_frame(key, state)])

        with ui.column().classes('w-full h-full flex-1 justify-between gap-4 p-2'):
            with ui.column().classes('w-full gap-2 shrink-0'):
                ui.label('Manual Controls').classes('text-2xl font-bold')
                ui.separator()

            with ui.column().classes('w-full gap-4 flex-1 justify-center'):
                ui.label('Servos').classes('text-sm font-semibold text-gray-400 uppercase tracking-wider mt-2')
                for key, name in SERVOS:
                    with ui.row().classes('w-full justify-between items-center gap-4'):
                        ui.label(name.upper()).classes('text-gray-400 font-medium whitespace-nowrap min-w-[140px]')
                        servo_state_labels[key] = ui.label('CLOSED').classes(
                            'text-red-400 font-mono text-lg whitespace-nowrap'
                        )
                        servo_labels[key] = ui.label('0.00').classes(
                            'text-gray-200 font-mono text-lg whitespace-nowrap')

                        ui.button('OPEN', on_click=lambda e, k=key: send_servo(k, SERVO_OPEN_POS)).props(
                            'color=green-7').classes(
                            'px-4 shrink-0 border border-white text-white font-bold')
                        ui.button('CLOSE', on_click=lambda e, k=key: send_servo(k, SERVO_CLOSED_POS)).props(
                            'color=red-7').classes(
                            'px-4 shrink-0 border border-white text-white font-bold')

                        ui.label('New value:').classes('text-gray-200 font-mono text-lg whitespace-nowrap')
                        servo_new_val = ui.label('0.00').classes(
                            'text-gray-200 font-mono text-lg whitespace-nowrap min-w-[50px]')

                        slider = (
                            ui.slider(min=0, max=100, value=0, step=0.1)
                            .bind_value_to(
                                servo_new_val,
                                'text',
                                forward=lambda v: f'{v:.2f}',
                            )
                            .classes('flex-1')
                        )
                        ui.button('SET', on_click=lambda e, k=key, s=slider: send_servo(k, s.value)).props(
                            'color=amber-6').classes(
                            'px-4 shrink-0 border border-white text-black font-bold')

                ui.separator().classes('my-2')
                ui.label('Relays').classes(
                    'text-sm font-semibold text-gray-400 uppercase tracking-wider'
                )
                for key, name in RELAYS:
                    with ui.row().classes('w-full justify-between items-center gap-4'):
                        ui.label(name.upper()).classes('text-gray-400 font-medium whitespace-nowrap min-w-[140px]')
                        relay_labels[key] = ui.label('CLOSED').classes(
                            'text-red-400 font-mono text-lg whitespace-nowrap')
                        ui.space().classes('flex-1')

                        ui.label('Last command:').classes('text-gray-200 font-mono text-lg whitespace-nowrap')
                        relay_new_val = ui.label('NONE').classes(
                            'text-yellow-400 font-mono text-lg whitespace-nowrap min-w-[60px]')

                        ui.button('OPEN', on_click=lambda e, k=key, l=relay_new_val: send_relay(k, 'OPEN', l)).props(
                            'color=green-7').classes(
                            'px-4 shrink-0 border border-white text-white font-bold')
                        ui.button('CLOSE',
                                  on_click=lambda e, k=key, l=relay_new_val: send_relay(k, 'CLOSE', l)).props(
                            'color=red-7').classes(
                            'px-4 shrink-0 border border-white text-white font-bold')

            ui.separator().classes('my-2')

    def automatic_controls_card():
        async def ignition_seq():
            await send_frames([servo_frame('oxidizer_valve', SERVO_OPEN_POS)])
            await asyncio.sleep(0.3)
            await send_frames([servo_frame('fuel_valve', SERVO_OPEN_POS)])
            await asyncio.sleep(0.3)
            await send_frames([relay_frame('igniter', 'OPEN')])

        def toggle_pressurize():
            auto_state['pressurize_active'] = not auto_state['pressurize_active']
            auto_btns['pressurize'].props(f'color={"green-7" if auto_state["pressurize_active"] else "grey-9"}')
            if auto_state['pressurize_active']:
                log_line("Auto Procedure: Pressurize Oxidizer STARTED")
            else:
                log_line("Auto Procedure: Pressurize Oxidizer STOPPED")

        with ui.column().classes('w-full h-full flex-1 justify-between gap-4 p-2'):
            with ui.column().classes('w-full gap-2 shrink-0'):
                ui.label('Automatic Controls').classes('text-2xl font-bold')
                ui.separator()

            with ui.row().classes('w-full flex-1 no-wrap gap-4 items-stretch'):
                with ui.column().classes('w-1/2 flex-1 gap-4 overflow-y-auto pr-2'):
                    ui.label('Status').classes('text-sm font-semibold text-gray-400 uppercase tracking-wider')

                    with ui.column().classes('w-full gap-2 bg-zinc-900/50 p-3 rounded-lg border border-zinc-800'):
                        with ui.row().classes('items-center gap-3 w-full'):
                            create_led('status_preflight')
                            ui.label('PREFLIGHT').classes('font-mono font-semibold text-gray-200')
                        with ui.row().classes('items-center gap-3 w-full'):
                            create_led('status_burn')
                            ui.label('BURN').classes('font-mono font-semibold text-gray-200')
                        with ui.row().classes('items-center gap-3 w-full'):
                            create_led('status_descend')
                            ui.label('DESCEND').classes('font-mono font-semibold text-gray-200')

                    ui.separator().classes('my-1')

                    ui.label('Checklist').classes('text-sm font-semibold text-gray-400 uppercase tracking-wider')

                    checklist_items = [
                        ('ox_filled', 'Oxidizer filled'),
                        ('fuel_filled', 'Fuel filled'),
                        ('intakes_closed', 'Intakes closed'),
                        ('ox_pressurized', 'Oxidizer pressurized'),
                        ('ignition', 'Ignition'),
                        ('parachute', 'Parachute'),
                    ]

                    with ui.column().classes(
                            'w-full gap-2.5 bg-zinc-900/50 p-3 rounded-lg border border-zinc-800 flex-1 justify-around'):
                        for key, label in checklist_items:
                            with ui.row().classes('items-center justify-between w-full'):
                                ui.label(label).classes('font-medium text-gray-300')
                                create_led(f'check_{key}')

                ui.separator().props('vertical').classes('bg-gray-800')
                with ui.column().classes('w-1/2 flex-1 justify-start gap-4 overflow-y-auto pl-2'):
                    auto_btns['start'] = ui.button('Automatic Independent Start Procedure').props(
                        'color=grey-9').classes('w-full border border-white text-white font-bold')
                    ui.separator()
                    auto_btns['fill_ox'] = ui.button('Fill oxidizer tanks', on_click=lambda: background_tasks.create(
                        send_frames([servo_frame('oxidizer_intake', SERVO_OPEN_POS)]))).props('color=grey-9').classes(
                        'w-full border border-white text-white font-bold')
                    auto_btns['fill_fuel'] = ui.button('Fill fuel tanks', on_click=lambda: background_tasks.create(
                        send_frames([servo_frame('fuel_intake', SERVO_OPEN_POS)]))).props('color=grey-9').classes(
                        'w-full border border-white text-white font-bold')
                    auto_btns['pressurize'] = ui.button('Pressurize Oxidizer', on_click=toggle_pressurize).props(
                        'color=grey-9').classes('w-full border border-white text-white font-bold')
                    auto_btns['ignition'] = ui.button('Main Engine Ignition',
                                                      on_click=lambda: background_tasks.create(ignition_seq())).props(
                        'color=grey-9').classes('w-full border border-white text-white font-bold')
                    ui.separator()
                    auto_btns['parachute'] = ui.button('Parachute Arm&Deploy', on_click=lambda: background_tasks.create(
                        send_frames([relay_frame('parachute', 'OPEN')]))).props('color=grey-9').classes(
                        'w-full border border-white text-white font-bold')

                    auto_btns['fill_fuel'].disable()
                    auto_btns['pressurize'].disable()
                    auto_btns['ignition'].disable()
                    auto_btns['parachute'].disable()

            ui.separator().classes('my-2')

    ui.dark_mode().enable()
    ui.query('.nicegui-content').classes('p-0 gap-0')
    with ui.column().classes('w-full h-screen p-4 gap-4 no-wrap box-border'):
        with ui.row().classes('w-full items-center shrink-0'):
            ui.label('Telemetry').classes('text-3xl font-bold')

        with ui.row().classes('w-full flex-1 no-wrap gap-4 min-h-0 items-stretch'):
            with ui.column().classes('w-full flex-1 h-full min-h-0 justify-between gap-4'):
                with ui.card().classes('w-full flex-1 justify-between'):
                    ui.label('Status').classes('text-2xl font-bold')
                    ui.separator()

                    ui.label('Sensors').classes('text-xl font-bold')
                    ui.separator()
                    for key, title, _unit in SENSORS:
                        sensor_labels[key] = row(title)

                    ui.label('Servos').classes('text-xl font-bold')
                    ui.separator()
                    for key, title in SERVOS:
                        status_servo_labels[key] = led_row(title, key)

                    ui.label('Relays').classes('text-xl font-bold')
                    ui.separator()
                    for key, title in RELAYS:
                        status_relay_labels[key] = led_row(title, key)
            with ui.column().classes('w-full flex-3 min-h-0 justify-between gap-4'):
                with ui.card().classes('w-full flex-1 flex flex-col min-h-0'):
                    ui.label('Flight Chart').classes('text-xl font-bold')
                    with ui.row().classes('w-full flex-1 no-wrap gap-4 min-h-0 items-stretch'):
                        with ui.column().classes('w-1/5 h-full justify-around bg-zinc-900/50 p-3 rounded-lg border border-zinc-800 shrink-0'):
                            with ui.row().classes('w-full justify-between items-center'):
                                ui.label('Altitude').classes('text-gray-400 font-semibold')
                                chart_alt_label = ui.label('0.00 m').classes('font-mono text-lg text-gray-200')
                            with ui.row().classes('w-full justify-between items-center'):
                                ui.label('Speed').classes('text-gray-400 font-semibold')
                                chart_speed_label = ui.label('0.00 m/s').classes('font-mono text-lg text-gray-200')
                            with ui.row().classes('w-full justify-between items-center'):
                                ui.label('Tilt Angle').classes('text-gray-400 font-semibold')
                                chart_tilt_label = ui.label('0.00 °').classes('font-mono text-lg text-gray-200')

                        with ui.column().classes('w-2/3 h-full min-h-0 flex-1'):
                            ui.echart({
                                'backgroundColor': 'transparent',
                                'xAxis': {
                                    'type': 'value',
                                    'name': 'Position',
                                    'position': 'center',
                                    'axisLine': {'onZero': True},
                                    'minorTick': {'show': True},
                                },
                                'yAxis': {
                                    'type': 'value',
                                    'name': 'Altitude',
                                    'position': 'center',
                                    'axisLine': {'onZero': True},
                                    'minorTick': {'show': True},
                                },
                                'series': [{
                                    'type': 'line',
                                    'data': [],
                                }],
                            }).classes('w-full h-full min-h-0')

                    with ui.card().classes('w-full flex-1 flex flex-col min-h-0 overflow-y-auto'):
                        with ui.column().classes(
                                'w-full h-full justify-center items-center text-gray-500 gap-2') as placeholder_panel:
                            ui.icon('tune', size='64px')
                            ui.label('Select a control panel from Manual Control menu').classes('text-lg font-semibold')

                        with ui.column().classes('w-full h-full') as manual_panel:
                            manual_controls_card()

                        with ui.column().classes('w-full h-full') as auto_panel:
                            automatic_controls_card()

            with ui.column().classes('w-full flex-1 h-full min-h-0 justify-between gap-4'):
                with ui.card().classes('w-full flex-1 flex flex-col justify-between'):
                    with ui.column().classes('w-full gap-2 flex-1 flex flex-col'):
                        ui.label('System Logs').classes('text-xl font-bold')
                        ui.separator()
                        with ui.row().classes('items-center gap-6 shrink-0'):
                            count_label = ui.label('Frames: 0').classes('font-mono')
                            age_label = ui.label('Last frame: never').classes('font-mono text-red-400')
                        frame_log = ui.log(max_lines=50).classes('w-full flex-1 min-h-0 bg-zinc-900 rounded p-2')

                with ui.card().classes('w-full flex-1 flex flex-col justify-between'):
                    ui.label('Manual Control').classes('text-2xl font-bold')
                    ui.separator()
                    with ui.column().classes('w-full gap-2 gap-y-6 flex-1 justify-start items-stretch'):
                        btn_manual = ui.button('Manual controls').classes(
                            'w-full h-full border border-white text-white font-bold')
                        btn_auto = ui.button('Automatic controls').classes(
                            'w-full h-full border border-white text-white font-bold')

    active_panel = {'name': 'manual'}

    def update_panels():
        name = active_panel['name']
        manual_panel.set_visibility(name == 'manual')
        auto_panel.set_visibility(name == 'auto')
        placeholder_panel.set_visibility(name is None)

        btn_manual.props(
            f'color={"grey-6" if name == "manual" else "grey-9"} text-{"black" if name == "manual" else "white"}')
        btn_auto.props(
            f'color={"grey-6" if name == "auto" else "grey-9"} text-{"black" if name == "auto" else "white"}')

    def toggle_panel(name: str):
        if active_panel['name'] == name:
            active_panel['name'] = None
        else:
            active_panel['name'] = name
        update_panels()

    btn_manual.on('click', lambda e: toggle_panel('manual'))
    btn_auto.on('click', lambda e: toggle_panel('auto'))

    update_panels()

    def update_checklist_log(key, is_ready, display_name):
        if is_ready and not checklist_state[key]:
            log_line(f"Checklist Item READY: {display_name}")
        checklist_state[key] = is_ready

    def refresh():
        now = time.time()
        count_label.text = f"Frames: {stats['count']}"
        if stats['last_time'] is None:
            age_label.text = 'Last frame: never'
            fresh = False
        else:
            age = now - stats['last_time']
            age_label.text = f"Last frame: {age:.1f} s ago"
            fresh = age < 2.0
        age_label.classes(
            add='text-green-400' if fresh else 'text-red-400',
            remove='text-red-400' if fresh else 'text-green-400',
        )
        while log_buffer:
            frame_log.push(log_buffer.popleft())

        current_alt = data.get('altitude', 0.0)
        if current_alt != stats['last_alt']:
            dt = now - stats['last_alt_time']
            if dt > 0:
                stats['speed'] = abs(current_alt - stats['last_alt']) / dt
            stats['last_alt'] = current_alt
            stats['last_alt_time'] = now
        else:
            if now - stats['last_alt_time'] > 0.5:
                stats['speed'] = 0.0
        for key, _ in SERVOS:
            value = data[key]
            text = format_Data(value, '.1f')
            servo_labels[key].text = text
            status_servo_labels[key].text = text
            try:
                is_open = float(value) != SERVO_CLOSED_POS
            except (TypeError, ValueError):
                is_open = False
            set_open_state(servo_state_labels[key], is_open)
            set_led_color(f'status_{key}', 'green' if is_open else 'red')

        for key, _ in RELAYS:
            is_open = bool(data[key])
            set_open_state(relay_labels[key], is_open)
            status_relay_labels[key].text = 'OPEN' if is_open else 'CLOSED'
            set_led_color(f'status_{key}', 'green' if is_open else 'red')

        for key, _, unit in SENSORS:
            sensor_labels[key].text = f"{format_Data(data[key], '.2f')} {unit}"

        ox_lvl = float(data.get('oxidizer_level', 0.0))
        fuel_lvl = float(data.get('fuel_level', 0.0))
        ox_press = float(data.get('oxidizer_pressure', 0.0))
        fuel_intake_closed = float(data.get('fuel_intake', 0.0)) == SERVO_CLOSED_POS
        ox_intake_closed = float(data.get('oxidizer_intake', 0.0)) == SERVO_CLOSED_POS
        igniter_active = bool(data.get('igniter', False))
        parachute_active = bool(data.get('parachute', False))
        speed = stats['speed']
        chart_alt_label.text = f"{format_Data(data.get('altitude', 0.0), '.2f')} m"
        chart_speed_label.text = f"{speed} m/s"
        chart_tilt_label.text = f"{format_Data(data.get('nosecone_tilt', 0.0), '.2f')} °"

        ox_lvl = float(data.get('oxidizer_level', 0.0))
        fuel_lvl = float(data.get('fuel_level', 0.0))
        fuel_intake_closed = float(data.get('fuel_intake', 0.0)) == SERVO_CLOSED_POS
        ox_intake_closed = float(data.get('oxidizer_intake', 0.0)) == SERVO_CLOSED_POS

        if ox_lvl >= 100.0 and not ox_intake_closed:
            if now - auto_state['last_ox_close_time'] > 1.0:
                background_tasks.create(send_frames([servo_frame('oxidizer_intake', SERVO_CLOSED_POS)]))
                auto_state['last_ox_close_time'] = now

        if fuel_lvl >= 100.0 and not fuel_intake_closed:
            if now - auto_state['last_fuel_close_time'] > 1.0:
                background_tasks.create(send_frames([servo_frame('fuel_intake', SERVO_CLOSED_POS)]))
                auto_state['last_fuel_close_time'] = now

        update_checklist_log('ox_filled', ox_lvl >= 100.0, "Oxidizer filled")
        update_checklist_log('fuel_filled', fuel_lvl >= 100.0, "Fuel filled")
        update_checklist_log('intakes_closed', fuel_intake_closed and ox_intake_closed, "Intakes closed")
        update_checklist_log('ox_pressurized', 57.0 <= ox_press <= 59.0, "Oxidizer pressurized")
        update_checklist_log('ignition', igniter_active and fuel_lvl > 0.0 and ox_lvl > 0.0, "Ignition")
        update_checklist_log('parachute', parachute_active, "Parachute")

        if ox_lvl >= 100.0:
            set_led_color('check_ox_filled', 'green')
        elif ox_lvl > 0.0:
            set_led_blink('check_ox_filled', 'yellow', 'red')
        else:
            set_led_color('check_ox_filled', 'red')

        if fuel_lvl >= 100.0:
            set_led_color('check_fuel_filled', 'green')
        elif fuel_lvl > 0.0:
            set_led_blink('check_fuel_filled', 'yellow', 'red')
        else:
            set_led_color('check_fuel_filled', 'red')

        if fuel_intake_closed and ox_intake_closed:
            set_led_color('check_intakes_closed', 'green')
        else:
            set_led_color('check_intakes_closed', 'red')

        if 55.5 <= ox_press <= 59.5:
            set_led_color('check_ox_pressurized', 'green')
        elif ox_press > 0.0:
            set_led_color('check_ox_pressurized', 'yellow')
        else:
            set_led_color('check_ox_pressurized', 'red')

        if igniter_active and fuel_lvl > 0.0 and ox_lvl > 0.0:
            set_led_color('check_ignition', 'green')
        else:
            set_led_color('check_ignition', 'red')

        if parachute_active:
            set_led_color('check_parachute', 'green')
        elif speed < 30.0:
            set_led_color('check_parachute', 'blue')
        else:
            set_led_color('check_parachute', 'red')

        is_burn_phase = igniter_active and (fuel_lvl > 0.0 or ox_lvl > 0.0)
        is_descend_phase = parachute_active or (
                not is_burn_phase and ox_lvl <= 0.0 and fuel_lvl <= 0.0 and data.get('altitude', 0.0) > 10.0)
        is_preflight_phase = not is_burn_phase and not is_descend_phase

        set_led_color('status_preflight', 'green' if is_preflight_phase else 'off')
        set_led_color('status_burn', 'green' if is_burn_phase else 'off')
        set_led_color('status_descend', 'green' if is_descend_phase else 'off')

        if 'fill_fuel' in auto_btns:
            if ox_lvl >= 100.0:
                auto_btns['fill_fuel'].enable()
            else:
                auto_btns['fill_fuel'].disable()
            if fuel_lvl >= 100.0:
                auto_btns['pressurize'].enable()

            else:
                auto_btns['pressurize'].disable()
                if auto_state['pressurize_active']:
                    auto_state['pressurize_active'] = False
                    auto_btns['pressurize'].props('color=grey-9')
                    log_line("Auto Procedure: Pressurize Oxidizer STOPPED (Pre-conditions not met)")

            if 55.5 <= ox_press <= 59.5:
                auto_btns['ignition'].enable()
            else:
                auto_btns['ignition'].disable()

            if fuel_lvl == 0.0 or ox_lvl == 0.0:
                auto_btns['parachute'].enable()

            curr_heater = bool(data.get('oxidizer_heater', False))

            if auto_state['pressurize_active']:
                if ox_press < 55.5 and not curr_heater:
                    if now - auto_state['last_heater_cmd_time'] > 1.0:
                        background_tasks.create(send_frames([relay_frame('oxidizer_heater', 'OPEN')]))
                        auto_state['last_heater_cmd_time'] = now
                elif ox_press > 59.5 and curr_heater:
                    if now - auto_state['last_heater_cmd_time'] > 1.0:
                        background_tasks.create(send_frames([relay_frame('oxidizer_heater', 'CLOSE')]))
                        auto_state['last_heater_cmd_time'] = now

    def safe_refresh():
        try:
            refresh()
        except Exception:
            traceback.print_exc()

    ui.timer(refresh_s, safe_refresh)


@ui.page('/')
def index():
    prep_ui(telemetry)


async def comm_loop(cm: CommunicationManager):
    timeouts = 0
    while True:
        try:
            frame = await asyncio.to_thread(cm.receive)
            handle_frame(frame, registered=True)
        except TransportTimeoutError:
            timeouts += 1
        except UnregisteredCallbackError as e:
            handle_frame(e.frame, registered=False)
        except Exception:
            traceback.print_exc()
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    cm = CommunicationManager()
    cm.change_transport_type(TransportType.TCP)

    try:
        cm.connect(TcpSettings(PROXY_HOST, PROXY_PORT))
    except Exception:
        traceback.print_exc()
        raise

    app.on_startup(lambda: background_tasks.create(comm_loop(cm)))
    ui.run(port=UI_PORT, title='Telemetry', reload=False)