# Установка BIND

## Практические сценарии

### 1. Установка BIND

Установка пакета `bind9` и утилит для диагностики DNS. Пакет `dnsutils` содержит ключевые инструменты (`dig`, `nslookup`), необходимые для проверки и отладки DNS-сервера. Подробнее об их использовании см. в заметке **[Диагностика DNS](../../../Diagnostics/Networking/dns_diagnostics.md)**.

```bash
sudo apt-get update
sudo apt-get install -y bind9 dnsutils
sudo systemctl enable --now bind9
```
