# iSCSI: Настройка Target (Сервер)

> **Надёжность: 10/10** (Проверено на LIO и tgt)
> **Актуальность: 2026-07** (Ядро Linux 6.x+, LIO/targetcli)

**iSCSI Target (Таргет)** — серверный компонент, экспортирующий локальные дисковые ресурсы (физические диски, LVM-тома или файлы) инициаторам по сети. В современном Linux стандартом является реализация **LIO**, работающая на уровне ядра.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Backstore** | Тип и путь к реальному хранилищу данных (fileio, block, pscsi, ramdisk). |
| **TPG (Target Portal Group)** | Контейнер для настроек группы порталов, LUN и ACL. |
| **ACL (Access Control List)** | Список IQN инициаторов, которым разрешен доступ к конкретному таргету. |
| **Portal** | IP-адрес и порт (по умолчанию 3260), на которых таргет ожидает соединения. |
| **Targetcli** | Интерактивная оболочка для управления LIO таргетом. |

## Основные концепции

### Типы хранилищ (Backstores)
1.  **fileio**: Использование файла-образа на существующей ФС (медленнее, удобно для тестов).
2.  **block**: Прямое использование блочного устройства (диск, раздел, LVM). Рекомендуется для продакшена (максимальная производительность).
3.  **pscsi**: Прямой проброс SCSI-устройства (Pass-through).
4.  **ramdisk**: Хранилище в оперативной памяти (экстремальная скорость, данные теряются при перезагрузке).

### Безопасность
По умолчанию LIO требует явного указания IQN инициатора в ACL. Дополнительно рекомендуется использовать **CHAP** для аутентификации.

## Практические сценарии

### Сценарий 1: Настройка LIO (Современный стандарт)

LIO (linux-iscsi.org) — это подсистема ядра Linux для работы в режиме таргета.

#### 1. Установка
```bash
sudo apt update && sudo apt install targetcli-fb -y
# → Установка утилиты управления и демона rtslib-fb-targetctl
```

#### 2. Интерактивная настройка
Запустите `targetcli`:
```bash
sudo targetcli
```
Выполните последовательность команд (пример для LVM-тома):
```bash
# 1. Создание блочного хранилища
/backstores/block create name=disk1 dev=/dev/vg_storage/lv_iscsi_01

# 2. Создание таргета
/iscsi create iqn.2026-07.com.example:target01

# 3. Привязка LUN к TPG
/iscsi/iqn.2026-07.com.example:target01/tpg1/luns create /backstores/block/disk1

# 4. Создание портала (слушать на всех интерфейсах)
/iscsi/iqn.2026-07.com.example:target01/tpg1/portals create 0.0.0.0

# 5. Настройка прав доступа (IQN инициатора)
/iscsi/iqn.2026-07.com.example:target01/tpg1/acls create iqn.2026-07.com.example:initiator01

# 6. Сохранение и выход
exit
# → Configuration saved to /etc/rtslib-fb-target/saveconfig.json
```

---

### Сценарий 2: Настройка через tgt (Legacy)

`tgt` работает в user-space. В 2026 году считается устаревшим, но всё еще встречается в старых системах.

#### 1. Установка и базовая конфигурация
```bash
sudo apt install tgt -y
```
Создайте файл `/etc/tgt/conf.d/iscsi.conf`:
```apache
<target iqn.2026-07.com.example:storage.legacy>
    backing-store /dev/vg_storage/lv_iscsi_legacy
    initiator-address 192.168.1.0/24
</target>
```
#### 2. Запуск
```bash
sudo systemctl restart tgt
sudo systemctl enable tgt
```

## Дополнительная информация

### Настройка Firewall
iSCSI использует порт **3260/tcp**.

**Firewalld:**
```bash
sudo firewall-cmd --permanent --add-port=3260/tcp
sudo firewall-cmd --reload
# → success
```

### Персистентность настроек (LIO)
В отличие от `tgt`, где конфиг хранится в текстовом файле, LIO сохраняет состояние в двоичном JSON. Убедитесь, что сервис автозагрузки активен:
```bash
sudo systemctl enable target
```

### См. также
- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — подключение клиента к созданному таргету.
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — тюнинг сетевого стека и параметров I/O.
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — создание нескольких путей для отказоустойчивости.
