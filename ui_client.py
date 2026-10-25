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

stats = {'count': 0, 'last_time': 0}
log_buffer = deque(maxlen=200)


def log_line(text: str):
    log_buffer.append(f"{time.strftime('%H:%M:%S')}  {text}")


def telemetry_update(frame: Frame):
    payload = frame.payload
    if isinstance(payload, (tuple, list)):
        payload = payload[0] if payload else None
    if payload is None:
        return

    if frame.device_type == ids.DeviceID.SERVO:
        name = SERVO_NAMES.get(frame.device_id)
        value = payload
    elif frame.device_type == ids.DeviceID.RELAY:
        name = RELAY_NAMES.get(frame.device_id)
        value = payload == ids.OperationID.RELAY.value.OPEN
    elif frame.device_type == ids.DeviceID.SENSOR:
        name = SENSOR_NAMES.get(frame.device_id)
        value = payload
    else:
        return

    if name is None:
        print(f"unknown device: {frame.device_type} {frame.device_id}")
        return

    telemetry[name] = value


def handle_frame(frame: Frame, registered: bool):
    stats['count'] += 1
    stats['last_time'] = time.time()
    telemetry_update(frame)


SERVOS = [
    ('fuel_intake', 'Fuel intake'),
    ('oxidizer_intake', 'Oxidizer intake'),
    ('fuel_valve', 'Fuel valve'),
    ('oxidizer_valve', 'Oxidizer valve'),
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
                 ids.DataTypeID.INT16,
                 ids.OperationID.RELAY.value.POSITION,
                 operation)


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

    def row(label_text: str):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label(label_text).classes('text-gray-400')
            return ui.label('-').classes('font-mono text-lg')

    def set_open_state(lbl, is_open: bool):
        lbl.text = 'OPEN' if is_open else 'CLOSED'
        lbl.classes(
            add='text-green-400' if is_open else 'text-red-400',
            remove='text-red-400' if is_open else 'text-green-400',
        )

    def preflight_controls_card():
        staged_servos = {}

        async def send_staged():
            frames = [servo_frame(k, v) for k, v in staged_servos.items()]
            staged_servos.clear()
            await send_frames(frames)

        async def send_servo(key: str, position):
            await send_frames([servo_frame(key, position)])

        async def send_relay(key: str, state: str, label):
            label.set_text(state)
            await send_frames([relay_frame(key, state)])

        with ui.column().classes('w-full h-full flex-1 justify-between gap-4 p-2'):
            with ui.column().classes('w-full gap-2 shrink-0'):
                with ui.row().classes('w-full justify-between'):
                    ui.label('Preflight Controls').classes('text-2xl font-bold')
                    ui.button('SEND COMMANDS', on_click=send_staged).classes('bg-blue-600 text-white font-bold px-8 py-2 rounded-lg')
                ui.separator()

            with ui.column().classes('w-full gap-4 flex-1 justify-center'):
                ui.label('Servos').classes('text-sm font-semibold text-gray-400 uppercase tracking-wider mt-2')
                for key, name in SERVOS:
                    with ui.row().classes('w-full justify-between items-center gap-4'):
                        ui.label(name.upper()).classes('text-gray-400 font-medium whitespace-nowrap min-w-[140px]')
                        servo_state_labels[key] = ui.label('CLOSED').classes(
                            'text-red-400 font-mono text-lg whitespace-nowrap'
                        )
                        servo_labels[key] = ui.label('0.00').classes('text-gray-200 font-mono text-lg whitespace-nowrap')

                        ui.button('OPEN', on_click=lambda k=key: send_servo(k, SERVO_OPEN_POS)).classes('px-4 shrink-0')
                        ui.button('CLOSE', on_click=lambda k=key: send_servo(k, SERVO_CLOSED_POS)).classes('px-4 shrink-0')

                        ui.label('New value:').classes('text-gray-200 font-mono text-lg whitespace-nowrap')
                        servo_new_val = ui.label('0.00').classes('text-gray-200 font-mono text-lg whitespace-nowrap min-w-[50px]')

                        slider = (
                            ui.slider(min=0, max=100, value=0, step=0.1)
                            .bind_value_to(
                                servo_new_val,
                                'text',
                                forward=lambda v: f'{v:.2f}',
                            )
                            .classes('flex-1')
                        )
                        slider.on('update:model-value', lambda e, k=key: staged_servos.update({k: e.args}))

                ui.separator().classes('my-2')
                ui.label('Relays').classes(
                    'text-sm font-semibold text-gray-400 uppercase tracking-wider'
                )
                for key, name in RELAYS:
                    with ui.row().classes('w-full justify-between items-center gap-4'):
                        ui.label(name.upper()).classes('text-gray-400 font-medium whitespace-nowrap min-w-[140px]')
                        relay_labels[key] = ui.label('CLOSED').classes('text-red-400 font-mono text-lg whitespace-nowrap')
                        ui.space().classes('flex-1')

                        ui.label('Last command:').classes('text-gray-200 font-mono text-lg whitespace-nowrap')
                        relay_new_val = ui.label('NONE').classes('text-yellow-400 font-mono text-lg whitespace-nowrap min-w-[60px]')

                        ui.button('OPEN', on_click=lambda k=key, l=relay_new_val: send_relay(k, 'OPEN', l)).classes('px-4 shrink-0')
                        ui.button('CLOSE', on_click=lambda k=key, l=relay_new_val: send_relay(k, 'CLOSE', l)).classes('px-4 shrink-0')

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
                        status_servo_labels[key] = row(title)

                    ui.label('Relays').classes('text-xl font-bold')
                    ui.separator()
                    for key, title in RELAYS:
                        status_relay_labels[key] = row(title)

            with ui.column().classes('w-full flex-3 min-h-0 justify-between gap-4'):
                with ui.card().classes('w-full flex-1 flex flex-col min-h-0'):
                    ui.label('Chart').classes('text-xl font-bold')
                    ui.echart({
                        'backgroundColor': 'transparent',
                        'xAxis': {
                            'type': 'value',
                            'name': 'x',
                            'position': 'center',
                            'axisLine': {'onZero': True},
                            'minorTick': {'show': True},
                        },
                        'yAxis': {
                            'type': 'value',
                            'name': 'y',
                            'position': 'center',
                            'axisLine': {'onZero': True},
                            'minorTick': {'show': True},
                        },
                        'series': [{
                            'type': 'line',
                            'data': [],
                        }],
                    }).classes('w-full h-full min-h-0')
                with ui.card().classes('w-full flex-1 flex flex-col min-h-0'):
                    preflight_controls_card()

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
                    with ui.column().classes('w-full gap-2 flex-1 justify-around'):
                        ui.button('Preflight controls').classes('w-full')
                        ui.button('Burn manipulation').classes('w-full')
                        ui.button('Manual relay control').classes('w-full')

    def refresh():
        count_label.text = f"Frames: {stats['count']}"
        if stats['last_time'] is None:
            age_label.text = 'Last frame: never'
            fresh = False
        else:
            age = time.time() - stats['last_time']
            age_label.text = f"Last frame: {age:.1f} s ago"
            fresh = age < 2.0
        age_label.classes(
            add='text-green-400' if fresh else 'text-red-400',
            remove='text-red-400' if fresh else 'text-green-400',
        )
        while log_buffer:
            frame_log.push(log_buffer.popleft())

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

        for key, _ in RELAYS:
            is_open = bool(data[key])
            set_open_state(relay_labels[key], is_open)
            set_open_state(status_relay_labels[key], is_open)

        for key, _, unit in SENSORS:
            sensor_labels[key].text = f"{format_Data(data[key], '.2f')} {unit}"

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
    log_line("comm_loop wystartowal")
    print("comm_loop wystartowal")
    timeouts = 0
    while True:
        try:
            frame = await asyncio.to_thread(cm.receive)
            handle_frame(frame, registered=True)
        except TransportTimeoutError:
            timeouts += 1
            if timeouts % 10 == 1:
                log_line(f"timeout receive (x{timeouts}), brak danych")
        except UnregisteredCallbackError as e:
            handle_frame(e.frame, registered=False)
        except Exception:
            traceback.print_exc()
            log_line(f"ERROR: {traceback.format_exc().splitlines()[-1]}")
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    print("uruchomiono ui_client")
    cm = CommunicationManager()
    cm.change_transport_type(TransportType.TCP)

    try:
        cm.connect(TcpSettings(PROXY_HOST, PROXY_PORT))
        print(f"polaczono z proxy {PROXY_HOST}:{PROXY_PORT}")
    except Exception:
        traceback.print_exc()
        raise

    app.on_startup(lambda: background_tasks.create(comm_loop(cm)))
    ui.run(port=UI_PORT, title='Telemetry', reload=False)