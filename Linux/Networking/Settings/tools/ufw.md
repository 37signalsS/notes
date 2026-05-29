# UFW — Uncomplicated Firewall

## Definitions

**UFW (Uncomplicated Firewall)** — это интерфейс для управления `iptables` (или `nftables` в современных дистрибутивах), разработанный для упрощения процесса настройки файрвола. Является стандартом по умолчанию в Ubuntu.

## Basic Concepts

### Принципы работы

1. **Default Deny Incoming:** по умолчанию весь входящий трафик должен быть запрещен.
2. **Default Allow Outgoing:** исходящий трафик обычно разрешен для работы обновлений и внешних запросов.
3. **Stateful Inspection:** UFW отслеживает состояние соединений.

### Основные команды

```bash
sudo ufw status                # Проверка статуса
sudo ufw enable                # Включение файрвола
sudo ufw disable               # Выключение файрвола
sudo ufw default deny incoming # Политика по умолчанию: запретить входящие
sudo ufw default allow outgoing # Политика по умолчанию: разрешить исходящие
```

## Practical Scenarios

### 1. Базовая настройка для веб-сервера

**Задача:** Запретить все входящие соединения, кроме SSH и порта приложения (8080).

```bash
# 1. Установка политик по умолчанию
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 2. Разрешение необходимых портов
sudo ufw allow 22/tcp          # SSH
sudo ufw allow 8080/tcp        # Приложение

# 3. Включение файрвола
sudo ufw enable

# 4. Проверка
sudo ufw status verbose
```

### 2. Ограничение доступа по IP

```bash
# Разрешить SSH только с конкретного IP
sudo ufw allow from 192.168.1.100 to any port 22
```

### 3. Удаление правил

```bash
# Удаление по номеру
sudo ufw status numbered
sudo ufw delete 2
```

## Additional Information

### Влияние на сканирование (Nmap)

При включенном файрволе с политикой `DROP` (по умолчанию в UFW), сканирование `nmap` значительно замедляется, так как сканер не получает ответов на пакеты и вынужден ждать таймаута. Порты будут отображаться в статусе `filtered`.

### Связанные темы

- **[Обзор файрволов](./firewall_common.md)** — сравнение инструментов
- **[iptables основы](./iptables_basics.md)** — низкоуровневая настройка
- **[nftables](../tools/nftables/practical_scenarios.md)** — современная альтернатива
