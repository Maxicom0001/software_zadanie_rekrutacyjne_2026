from communication_library.communication_manager import CommunicationManager, TransportType
from communication_library.tcp_transport import TcpSettings
from communication_library.frame import Frame
from communication_library import ids
from communication_library.exceptions import TransportTimeoutError, TransportError, UnregisteredCallbackError
import procedures


def on_altitude(frame: Frame):
    print(f"Registered frame received: {frame}")


def on_oxidizer(frame: Frame):
    print(f"Oxidzier level: {frame.payload}")


def on_servo(frame: Frame):
    print(f"Current servo position: {frame.payload}")

def empty(frame: Frame):
    return

if __name__ == "__main__":
    cm = CommunicationManager()  # Class responsible for communication handling
    cm.change_transport_type(TransportType.TCP)
    # We must create a frame that will serve as a pattern indicating what kind of frames we want to receive
    # During frame equality comparison the following fields are excluded: priority, data_type, payload
    # You can find more information in communication_library/frame.py

    oxidizer_frame = Frame(ids.BoardID.SOFTWARE,
                           ids.PriorityID.LOW,
                           ids.ActionID.FEED,
                           ids.BoardID.ROCKET,
                           ids.DeviceID.SENSOR,
                           1,  # altitude sensor
                           ids.DataTypeID.FLOAT,
                           ids.OperationID.SENSOR.value.READ)
    cm.register_callback(empty, oxidizer_frame)

    altitude_frame = Frame(ids.BoardID.SOFTWARE,
                           ids.PriorityID.LOW,
                           ids.ActionID.FEED,
                           ids.BoardID.ROCKET,
                           ids.DeviceID.SENSOR,
                           2,  # altitude sensor
                           ids.DataTypeID.FLOAT,
                           ids.OperationID.SENSOR.value.READ)
    cm.register_callback(empty, altitude_frame)

    altitude_frame = Frame(ids.BoardID.SOFTWARE,
                           ids.PriorityID.LOW,
                           ids.ActionID.FEED,
                           ids.BoardID.ROCKET,
                           ids.DeviceID.SENSOR,
                           3,  # altitude sensor
                           ids.DataTypeID.FLOAT,
                           ids.OperationID.SENSOR.value.READ)
    cm.register_callback(empty, altitude_frame)

    altitude_frame = Frame(ids.BoardID.SOFTWARE,
                           ids.PriorityID.LOW,
                           ids.ActionID.FEED,
                           ids.BoardID.ROCKET,
                           ids.DeviceID.SENSOR,
                           4,  # altitude sensor
                           ids.DataTypeID.FLOAT,
                           ids.OperationID.SENSOR.value.READ)
    cm.register_callback(empty, altitude_frame)
    cm.connect(TcpSettings("127.0.0.1", 3000))

    oxidizer_servo = procedures.change_servo_position(ids.PriorityID.LOW, 1, 0)
    cm.register_callback(on_servo, oxidizer_servo)

    cm.push(oxidizer_servo)
    cm.send()

    while True:
        try:
            frame = cm.receive()  # We can handle frames using callbacks or by getting frame right from receive() call
        except TransportTimeoutError:
            pass
        except UnregisteredCallbackError as e:
            print(f"unregistered frame received: {e.frame}")
