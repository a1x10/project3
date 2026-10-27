"""DNS-сервер: фильтрует по уровню защиты, пересылает остальное на upstream, пишет журнал."""
import logging
import socket

from dnslib import QTYPE, RCODE, RR, A, DNSRecord
from dnslib.server import BaseResolver, DNSServer

from . import blocklists, config, db

log = logging.getLogger("homeguard.dns")


class FilteringResolver(BaseResolver):
    def __init__(self, upstream: str = config.UPSTREAM_DNS, block_ip: str = config.BLOCK_IP):
        self.upstream = upstream
        self.block_ip = block_ip

    def resolve(self, request, handler):
        domain = str(request.q.qname).rstrip(".").lower()
        qtype = QTYPE[request.q.qtype]
        client = handler.client_address[0]
        level = db.get_setting("level")
        blocked, reason = blocklists.check(domain, level)

        reply = request.reply()
        if blocked:
            if request.q.qtype == QTYPE.A:
                reply.add_answer(RR(request.q.qname, QTYPE.A, rdata=A(self.block_ip), ttl=30))
            # для AAAA и прочего — пустой ответ, чтобы клиент пошёл на A-запись
            db.log_query(client, domain, qtype, "blocked", reason)
            return reply

        try:
            raw = request.send(self.upstream, 53, timeout=3)
            reply = DNSRecord.parse(raw)
            action = "allowed"
        except (socket.timeout, OSError):
            reply.header.rcode = RCODE.SERVFAIL
            action = "error"
        db.log_query(client, domain, qtype, action, None)
        return reply


def start(host: str = config.DNS_HOST, port: int = config.DNS_PORT,
          resolver: BaseResolver | None = None) -> DNSServer:
    server = DNSServer(resolver or FilteringResolver(), port=port, address=host)
    server.start_thread()
    log.info("DNS слушает %s:%d, upstream %s", host, port, config.UPSTREAM_DNS)
    return server
