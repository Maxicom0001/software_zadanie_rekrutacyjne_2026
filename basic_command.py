import asyncio

from communication_library.communication_manager import CommunicationManager, TransportType
from communication_library.tcp_transport import TcpSettings
from communication_library import ids
from communication_library.exceptions import TransportTimeoutError, UnregisteredCallbackError
import procedures


PROXY_HOST = "127.0.0.1"
PROXY_PORT = 3000


async def comm_loop(cm: CommunicationManager):
    while True:
        try:
            frame = await asyncio.to_thread(cm.receive)
            print(f"rframe: {frame}")
        except TransportTimeoutError:
            pass
        except UnregisteredCallbackError as e:
            print(f"uframe: {e.frame}")


async def main():
    cm = CommunicationManager()
    cm.change_transport_type(TransportType.TCP)
    cm.connect(TcpSettings(PROXY_HOST, PROXY_PORT))
    print(f"polaczono z proxy {PROXY_HOST}:{PROXY_PORT}")

    oxidizer_servo = procedures.change_servo_position(ids.PriorityID.LOW, 1, 0)
    cm.push(oxidizer_servo)
    cm.send()

    await comm_loop(cm)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass