from communication_library.communication_manager import CommunicationManager, TransportType
from communication_library.tcp_transport import TcpSettings
from communication_library.frame import Frame
from communication_library import ids
from communication_library.exceptions import TransportTimeoutError, TransportError, UnregisteredCallbackError

def change_servo_position(priority: ids.PriorityID, servo_id: int, target_value):
    return Frame(ids.BoardID.ROCKET,
                           priority,
                           ids.ActionID.SERVICE,
                           ids.BoardID.SOFTWARE,
                           ids.DeviceID.SERVO,
                           servo_id, # oxidizer heater
                           ids.DataTypeID.INT16,
                           ids.OperationID.SERVO.value.POSITION,
                           (target_value,)
                           )
