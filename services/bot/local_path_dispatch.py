"""Private local path-command notifications, verified against accepted TX history.

No SDK/device access, RX injection, polling, replay or new path inference.
Only an accepted path command or bounded typo hint can enter the live handler.
"""
from contextlib import closing
from dataclasses import dataclass
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import struct

from bot_commands import parse_command


@dataclass(frozen=True)
class LocalPathRequest:
    channel: int
    timestamp: int
    text: str


def read_accepted_path(path, identity, channels):
    """One exact read-only row. A local TX is never reception evidence."""
    if (not isinstance(identity, str) or len(identity) != 67 or not identity.startswith('tx-')
            or any(c not in '0123456789abcdef' for c in identity[3:])):
        raise ValueError('invalid_local_path_identity')
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=0.25)) as db:
        row=db.execute('SELECT id,transport_id,kind,channel_index,contact_prefix,text,'
            'sender_timestamp,outgoing,send_result,delivery_proven,source '
            'FROM outgoing WHERE id=?',(identity,)).fetchone()
    if row is None:
        raise ValueError('local_path_tx_not_found')
    own,transport,kind,channel,contact,text,stamp,outgoing,result,delivery,source=row
    if (own != identity or transport != identity or kind != 'channel' or type(channel) is not int
            or channel not in channels or contact is not None or outgoing != 1
            or result != 'accepted' or delivery != 0 or source != 'shared_transport'
            or not isinstance(text,str) or type(stamp) is not int or not 0<=stamp<=0xffffffff
            or parse_command(text) not in {'path','path_hint'}):
        raise ValueError('local_path_tx_not_accepted_path')
    raw=bytes([3,0,channel])+stamp.to_bytes(4,'little')+text.encode('utf-8','strict')
    if 'tx-'+hashlib.sha256(raw).hexdigest() != identity:
        raise ValueError('local_path_tx_identity_mismatch')
    return LocalPathRequest(channel,stamp,text)


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate_local_path_field')
        result[key]=value
    return result


class LocalPathServer:
    """Bounded private Unix socket; lifecycle owned by one live bot session.

    Notification ACK means receipt only, never RF/delivery or successful reply.
    Replies remain exclusively in the existing handler/claim/packet pipeline.
    """
    def __init__(self,path,handler,log):
        self.path=Path(path)
        self.handler,self.log=handler,log
        self.server=None
        self.identity=None
        self.tasks=set()

    async def start(self):
        if os.name!='posix' or not self.path.is_absolute() or len(os.fsencode(self.path))>100:
            raise ValueError('local_path_socket_not_native_private')
        parent=self.path.parent
        if parent.resolve()!=parent or not parent.is_dir() or parent.stat().st_uid!=os.getuid():
            raise ValueError('local_path_socket_parent')
        # An old inode may only be removed if it is our own refused socket.
        # Never unlink another live listener, symlink, regular file or owner.
        if os.path.lexists(self.path):
            before=self.path.lstat()
            if not stat.S_ISSOCK(before.st_mode) or before.st_uid!=os.getuid():
                raise ValueError('local_path_socket_foreign')
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
                probe.settimeout(0.25)
                try:probe.connect(str(self.path))
                except ConnectionRefusedError:pass
                else:raise ValueError('local_path_socket_already_live')
            after=self.path.lstat()
            if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):
                raise ValueError('local_path_socket_changed')
            self.path.unlink()
        # Its parent is private in HA; restrict the socket itself as well.
        if stat.S_IMODE(parent.stat().st_mode)&0o077:
            raise ValueError('local_path_socket_parent_not_private')
        self.server=await asyncio.start_unix_server(self._connection,str(self.path),limit=512)
        current=self.path.lstat()
        self.identity=(current.st_dev,current.st_ino)
        os.chmod(self.path,0o600)
        self.log('local_path_listener_ready')

    async def _connection(self,reader,writer):
        task=asyncio.current_task()
        if len(self.tasks)>=16:
            writer.close();return
        self.tasks.add(task)
        try:
            sock=writer.get_extra_info('socket')
            if hasattr(socket,'SO_PEERCRED'):
                _,uid,_=struct.unpack('3i',sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid!=os.getuid():raise ValueError('local_path_peer_owner')
            raw=await asyncio.wait_for(reader.readline(),timeout=2)
            if not raw.endswith(b'\n') or len(raw)>256:raise ValueError('local_path_notice_size')
            notice=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=_unique)
            if (not isinstance(notice,dict) or set(notice)!={'v','transport_id'}
                    or type(notice['v']) is not int or notice['v']!=1
                    or not isinstance(notice['transport_id'],str)):
                raise ValueError('local_path_notice_schema')
            writer.write(b'{"received":true}\n')
            await writer.drain()
            writer.close()
            await self.handler(notice['transport_id'])
        except (ValueError,UnicodeError,OSError,asyncio.TimeoutError,sqlite3.Error) as exc:
            self.log('local_path_notice_rejected',error_type=type(exc).__name__)
        finally:
            writer.close()
            self.tasks.discard(task)

    async def close(self):
        if self.server is not None:
            self.server.close();await self.server.wait_closed()
        for task in tuple(self.tasks):task.cancel()
        await asyncio.gather(*tuple(self.tasks),return_exceptions=True)
        if self.identity is not None and os.path.lexists(self.path):
            current=self.path.lstat()
            if (current.st_dev,current.st_ino)==self.identity and stat.S_ISSOCK(current.st_mode):
                self.path.unlink()
