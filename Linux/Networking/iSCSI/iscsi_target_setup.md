# iSCSI: Настройка Target

Руководство по установке и конфигурации серверной части (Target) iSCSI в Linux.

## Определение

**iSCSI Target (Таргет)** — это программный или аппаратный компонент, который предоставляет дисковые ресурсы (LUN) клиентам (инициаторам) по сети. В Linux наиболее популярными реализациями являются `tgt` (user-space) и `LIO` (kernel-space).

## Основные концепции

Теоретические основы архитектуры и адресации iSCSI описаны в документе **[Основные концепции iSCSI](./iscsi_concepts.md)**. Перед настройкой убедитесь, что:

- Выбрана подходящая реализация (`tgt` для простоты или `LIO` для производительности).
- Определен формат **IQN** для таргета.
- Подготовлено блочное устройство (физический диск, раздел, LVM-том или файл-образ).

## Практические сценарии

### Сценарий 1: Настройка через tgt (scsi-target-utils)

`tgt` — это стандартная реализация, работающая в пространстве пользователя. Рекомендуется для большинства задач благодаря простоте конфигурирования.

#### 1. Установка

```bash
sudo apt update && sudo apt install tgt -y
```

#### 2. Создание конфигурации таргета

Создайте файл `/etc/tgt/conf.d/iscsi.conf`:

```apache
# /etc/tgt/conf.d/iscsi.conf
<target iqn.2026-06.com.example:storage.lun1>
    # Путь к блочному устройству или файлу
    backing-store /dev/sdb
    
    # Ограничение доступа по IP (опционально)
    initiator-address 192.168.1.0/24
    
    # Настройка CHAP аутентификации (опционально)
    # incominguser username password
</target>
```

#### 3. Применение настроек

```bash
sudo systemctl restart tgt
sudo systemctl enable tgt
```

#### 4. Проверка состояния

```bash
sudo tgtadm --lld iscsi --mode target --op show
# → Выводит список активных таргетов, LUN и подключенных инициаторов
```

---

### Сценарий 2: Настройка через LIO (targetcli)

`LIO` — это реализация внутри ядра Linux, предоставляющая расширенные возможности и более высокую производительность.

#### 1. Установка

```bash
sudo apt update && sudo apt install targetcli-fb -y
```

#### 2. Интерактивная настройка

Запустите утилиту `targetcli`:

```bash
sudo targetcli
```

В интерфейсе `targetcli` выполните (пример для файла-образа):

```bash
# Создание хранилища (backstore)
/backstores/fileio create name=disk1 file_or_dev=/var/lib/iscsi_disks/disk1.img size=10G

# Создание iSCSI таргета (IQN создастся автоматически или укажите свой)
/iscsi create iqn.2026-06.com.example:target01

# Привязка LUN к таргету
/iscsi/iqn.2026-06.com.example:target01/tpg1/luns create /backstores/fileio/disk1

# Создание ACL для инициатора (IQN инициатора должен быть известен)
/iscsi/iqn.2026-06.com.example:target01/tpg1/acls create iqn.2026-06.com.example:client01

# Выход с сохранением
exit
```

## Дополнительная информация

### Настройка Firewall

iSCSI использует TCP-порт **3260**. Его необходимо открыть для доступа инициаторов.

**Через firewalld (рекомендуется):**

```bash
sudo firewall-cmd --permanent --add-port=3260/tcp
sudo firewall-cmd --reload
```

**Через ufw:**

```bash
sudo ufw allow 3260/tcp
```

### Безопасность и аутентификация

Для предотвращения несанкционированного доступа используйте **CHAP**. Подробная настройка CHAP на стороне клиента и сервера приведена в руководстве **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)**.

### См. также

- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — подключение к созданному таргету.
- **[Управление томами LVM](../../FileSystems/LVM/operations/lvm_disk_replacement.md)** — создание томов для использования в качестве LUN.
- **[Диагностика сети](../network_diagnostics_tools.md)** — проверка доступности порта 3260.
