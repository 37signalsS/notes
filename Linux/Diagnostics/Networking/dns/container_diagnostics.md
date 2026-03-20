# Диагностика DNS в контейнерах

DNS в контейнеризированных средах имеет особенности:

- **Kubernetes:** DNS обычно предоставляется [CoreDNS или NodeLocalDNS](../../../../Kubernetes/Networking/dns_deep_dive.md).

- **Docker:** Использует встроенный DNS на `127.0.0.11`. Проблемы решаются через проверку конфигурации демона и сети контейнера. Подробнее см. [Устранение проблем с DNS в Docker](../../../../Docker/Docker_troubleshooting/network_connectivity_issues.md#сценарий-4-проблемы-с-dns-в-контейнерах).

---

**Связанные темы:**

* [Базовая диагностика](./basic_diagnostics.md) — общие принципы
* [DNS в Kubernetes](../../../../Kubernetes/Networking/dns_deep_dive.md)
* [DNS в Docker](../../../../Docker/Docker_troubleshooting/network_connectivity_issues.md)
