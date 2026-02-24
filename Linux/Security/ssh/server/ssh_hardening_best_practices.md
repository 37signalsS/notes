# Укрепление безопасности SSH и лучшие практики

## Практические сценарии

### Настройка резервного SSH-доступа

Чтобы не потерять доступ к серверу после сбоя `firewall` или `NetworkManager`, можно настроить резервный экземпляр `sshd` на другом порту.

1. **Создайте копию конфигурации:**

    ```bash
    sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config_alt
    ```

2. **Отредактируйте `/etc/ssh/sshd_config_alt`:**

    ```ini
    Port 2222
    ListenAddress 192.168.100.10  # IP-адрес на интерфейсе управления
    PidFile /run/sshd-alt.pid
    # Убедитесь, что остальные настройки (например, PasswordAuthentication) безопасны
    ```

3. **Запустите второй экземпляр:**
    - **Вручную:** `sudo /usr/sbin/sshd -f /etc/ssh/sshd_config_alt`
    - **Через `systemd` (рекомендуется):** `sudo systemctl start sshd@alt.service` и `sudo systemctl enable sshd@alt.service` (может потребовать создания unit-файла).

### Изменение порта SSH при включенном SELinux

Простое изменение порта в `sshd_config` на системе с SELinux приведет к ошибке запуска службы.

1. **Измените порт** в `/etc/ssh/sshd_config` (например, на `5022`).
2. **Сообщите SELinux** о новом разрешенном порте для `sshd`:

    ```bash
    sudo semanage port -a -t ssh_port_t -p tcp 5022
    ```

3. **Перезапустите `sshd`:** `sudo systemctl restart sshd`.

## Дополнительная информация

### Инструменты для защиты от атак

- **[Fail2Ban](../../Tools/Fail2Ban.md):** Утилита, которая анализирует логи и автоматически блокирует IP-адреса, с которых ведутся [атаки перебора (brute-force)](../../../Security/Concepts/brute_force_attacks.md).
- **Endlessh:** SSH-ловушка ("tarpit"), которая "замораживает" ботов, бесконечно отправляя им SSH-баннер, но не завершая соединение. [GitHub-репозиторий](https://github.com/skeeto/endlessh).

### Сокрытие SSH-сервера с помощью [Port Knocking](SSH_Server_Security/port_knocking.md)
