# iSCSI: Настройка Target

## 1. Установка и настройка iSCSI Target

### Установка (Debian/Ubuntu)

```bash
sudo apt install tgt
```

Конфигурация — файл `/etc/tgt/conf.d/debian.conf`. Пример создания LUN:

```ini
# /etc/tgt/conf.d/iscsi-target.conf
<target iqn.2026-02.example:storage.lun1>
    backing-store /dev/sdb           # или путь к файлу-образу
    initiator-address 192.168.1.0/24 # разрешённые инициаторы
</target>
```

> **Важно:** iSCSI использует TCP-порт **3260**. Убедитесь, что он открыт в firewall:

```bash
sudo ufw allow 3260/tcp
# или для iptables
sudo iptables -A INPUT -p tcp --dport 3260 -j ACCEPT
```

После изменения конфигурации перезапустите службу:

```bash
sudo systemctl restart tgt
sudo systemctl enable tgt  # для автозагрузки при старте
```

### Проверка статуса Target

```bash
# Показать все таргеты
sudo tgtadm --lld iscsi --mode target --op show

# Проверить статус службы
systemctl status tgt
```

## 2. Альтернатива: LIO (targetcli)

`LIO` — встроенная в ядро Linux реализация iSCSI Target. Настройка через `targetcli`:

```bash
sudo apt install targetcli-fb
sudo targetcli
```

## Связанные документы

- **[Основные концепции](./iscsi_concepts.md)** — определения и архитектура
- **[Настройка Initiator](./iscsi_initiator_setup.md)** — подключение и использование
- **[Firewall](../../Settings/linux_firewall_management.md)** — настройка firewall
