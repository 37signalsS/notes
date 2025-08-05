# WireGuard: автоматическое обновление Endpoint при смене IP-адреса

Это руководство описывает, как настроить автоматическое обновление IP-адреса (Endpoint) на сервере WireGuard, который работает за NAT или имеет динамический IP.

## 1. Проблема

Если публичный IP-адрес сервера WireGuard меняется, клиенты теряют к нему доступ. Это происходит потому, что WireGuard при запуске определяет и "запоминает" свой IP-адрес. После смены IP сервер продолжает ожидать подключения на старом, уже неактуальном адресе, что приводит к разрыву VPN-соединения.

## 2. Решение

Решение заключается в создании systemd-таймера, который будет периодически выполнять скрипт. Скрипт принудительно переинициализирует слушающий сокет WireGuard, заставляя его определить новый IP-адрес без полного перезапуска службы.

**Предупреждение:** Этот метод решает проблему только на стороне сервера. Если вы используете файрвол (например, `ufw`, `iptables`) или облачные правила безопасности, вам также необходимо автоматизировать обновление правил для нового IP-адреса, чтобы разрешить трафик на порт WireGuard.

---

## 3. Реализация

### Шаг 1: Создание скрипта для перепривязки сокета

Скрипт будет выполнять команду `wg set`, которая заставляет WireGuard перечитать свой сетевой интерфейс и обновить IP-адрес.

Создайте файл `/usr/local/bin/wg-rebind.sh`:

```bash
#!/bin/bash
#
# Скрипт для принудительной перепривязки слушающего сокета WireGuard.
# Это необходимо для серверов, работающих с динамическим IP-адресом.

# --- Переменные ---
# Имя вашего WireGuard-интерфейса
readonly IFACE="wg0"
# Порт, который слушает WireGuard
readonly PORT="51820"
# --- Конец переменных ---

set -o nounset
set -o errexit
set -o pipefail

echo "Rebinding WireGuard interface '$IFACE' to port $PORT..."

# Команда `wg set ... listen-port` заставляет WireGuard перепривязать сокет,
# что позволяет ему определить новый публичный IP-адрес сервера.
wG set "$IFACE" listen-port "$PORT"

echo "Successfully rebound."
```

**Установите правильные права и сделайте скрипт исполняемым:**

```bash
# Сделать владельцем root и запретить запись
sudo chown root:root /usr/local/bin/wg-rebind.sh
sudo chmod 755 /usr/local/bin/wg-rebind.sh
```

### Шаг 2: Создание юнитов Systemd

Нам понадобится два файла: `service` для запуска скрипта и `timer` для его периодического вызова.

1.  **Создайте файл сервиса `/etc/systemd/system/wg-rebind.service`:**

    ```ini
    [Unit]
    Description=Rebind WireGuard listening port to its dynamic IP
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=oneshot
    ExecStart=/usr/local/bin/wg-rebind.sh
    ```

2.  **Создайте файл таймера `/etc/systemd/system/wg-rebind.timer`:**

    Этот таймер будет запускать сервис каждые 3 минуты.

    ```ini
    [Unit]
    Description=Run wg-rebind.service every 3 minutes

    [Timer]
    # Запустить через 1 минуту после загрузки
    OnBootSec=1min
    # Запускать каждые 3 минуты после активации
    OnUnitActiveSec=3min

    [Install]
    WantedBy=timers.target
    ```

### Шаг 3: Активация таймера

После создания файлов перезагрузите конфигурацию systemd, а затем включите и запустите таймер.

```bash
# Перечитать конфигурацию systemd
sudo systemctl daemon-reload

# Включить и немедленно запустить таймер
sudo systemctl enable --now wg-rebind.timer
```

---

## 4. Проверка работы

Вы можете убедиться, что таймер активен и успешно выполняется.

*   **Проверить статус таймера:**

    ```bash
    systemctl list-timers | grep wg-rebind
    ```
    Вывод должен показать, что таймер `wg-rebind.timer` активен и запланирован.

*   **Посмотреть логи выполнения сервиса:**

    ```bash
    journalctl -u wg-rebind.service -f
    ```
    Вы должны увидеть логи, подтверждающие успешное выполнение скрипта (`Successfully rebound`).
