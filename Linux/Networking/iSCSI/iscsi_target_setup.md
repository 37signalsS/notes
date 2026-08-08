# iSCSI: Настройка Target (Сервер)

Руководство по развертыванию, конфигурации и эксплуатации серверного компонента iSCSI в ОС Linux.

## Определения и сокращения

| Термин | Описание |
| :--- | :--- |
| **Target (Таргет)** | Серверный компонент, экспортирующий дисковые ресурсы по сети. |
| **Backstore** | Метод реализации хранилища в ядре (block, fileio, pscsi, ramdisk). |
| **TPG (Target Portal Group)** | Группа порталов, LUN и ACL, объединенных общей политикой доступа. |
| **LUN (Logical Unit Number)** | Логическая единица хранения, сопоставленная с конкретным Backstore. |
| **IQN (iSCSI Qualified Name)** | Уникальный идентификатор узла (инициатора или таргета). |
| **Portal** | IP-адрес и порт (3260/tcp), на которых таргет ожидает подключения. |
| **ACL (Access Control List)** | Список IQN инициаторов, которым разрешен вход в конкретную TPG. |
| **targetcli** | Основной инструмент администрирования стека LIO. |

## Основные концепции

### Архитектура LIO (linux-iscsi.org)

В современном Linux стандартом является **LIO** — реализация таргета на уровне ядра. Она взаимодействует с пользователем через псевдофайловую систему `configfs` (обычно монтируется в `/sys/kernel/config/target/`). Утилита `targetcli` предоставляет иерархическую оболочку для управления этой структурой.

### Типы хранилищ (Backstores)

1.  **block**: Использование блочных устройств напрямую (диски, LVM, Zvol). **Рекомендуется** для продакшена (минимальные задержки).
2.  **fileio**: Использование файла как виртуального диска. Удобно для тестов, но создает накладные расходы на ФС.
3.  **pscsi**: Прямой проброс физических SCSI-команд устройству (Pass-through).
4.  **ramdisk**: Хранилище в ОЗУ (данные теряются при перезагрузке).

## Практические сценарии

### Сценарий 1: Настройка LIO (Стандарт)

#### 1. Установка
```bash
sudo apt update && sudo apt install targetcli-fb -y
# Для RHEL/Rocky: sudo dnf install targetcli -y
```

#### 2. Конфигурация через targetcli
Запустите интерактивную оболочку: `sudo targetcli`.

```bash
# 1. Создание хранилища на базе LVM или раздела
/backstores/block create name=storage01 dev=/dev/vg_data/lv_iscsi

# 2. Создание таргета
/iscsi create iqn.2026-07.com.example:target01

# 3. Привязка портала (по умолчанию 0.0.0.0:3260)
/iscsi/iqn.2026-07.com.example:target01/tpg1/portals create 0.0.0.0

# 4. Сопоставление LUN с хранилищем
/iscsi/iqn.2026-07.com.example:target01/tpg1/luns create /backstores/block/storage01

# 5. Настройка доступа (ACL) для инициатора
/iscsi/iqn.2026-07.com.example:target01/tpg1/acls create iqn.2026-07.com.example:initiator01
```

### Сценарий 2: Настройка безопасности (CHAP)

LIO поддерживает одностороннюю и взаимную (Mutual) аутентификацию.

#### Односторонний CHAP (Таргет проверяет инициатора)
В `targetcli`:
```bash
cd /iscsi/iqn.2026-07.com.example:target01/tpg1/acls/iqn.2026-07.com.example:initiator01
set auth userid=user1
set auth password=secret_pass_123
```

#### Взаимный CHAP (Инициатор также проверяет таргет)
```bash
set auth mutual_userid=target_user
set auth mutual_password=target_pass_456
```

## Эксплуатация и обслуживание

### Резервное копирование конфигурации

Конфигурация LIO хранится в JSON-формате.

- **Путь по умолчанию:** `/etc/rtslib-fb-target/saveconfig.json`.
- **Ручное сохранение:** В `targetcli` выполнить `saveconfig`.
- **Создание бэкапа:**
  ```bash
  sudo targetcli saveconfig /root/iscsi_backup_$(date +%F).json
  ```
- **Восстановление:**
  ```bash
  sudo targetcli restoreconfig /root/iscsi_backup.json
  ```

### Персистентность
Убедитесь, что конфигурация автоматически загружается при старте системы:
```bash
sudo systemctl enable --now target
```
*Примечание:* В некоторых дистрибутивах сервис называется `targetcli.service`.

### Диагностика на стороне сервера

1.  **Проверка активных сессий:**
    ```bash
    ls /iscsi/iqn.2026-07.com.example:target01/tpg1/acls/iqn.2026-07.com.example:initiator01/
    # → Если папка 'info' содержит данные, сессия активна.
    ```
2.  **Просмотр структуры через sysfs:**
    ```bash
    ls -R /sys/kernel/config/target/
    ```
3.  **Логи ошибок:**
    ```bash
    sudo dmesg | grep -i target
    ```

## Дополнительная информация

### Сравнение с tgt (Legacy)

`tgt` (scsi-target-utils) — user-space реализация. В 2026 году считается устаревшей и используется только для поддержки старых систем или специфических эмуляций. LIO превосходит `tgt` по производительности и нативной интеграции с ядром.

### Интеграция и оптимизация

- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — подключение клиента.
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — тюнинг сетевого стека и параметров I/O.
- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — решение проблем связности.
- **[Настройка Firewall](../Settings/tools/firewalld.md)** — открытие порта 3260/tcp.
