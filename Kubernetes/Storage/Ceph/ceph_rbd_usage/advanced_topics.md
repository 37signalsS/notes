# RBD: Расширенные темы и оптимизация

Документ содержит углубленную информацию по настройке производительности, обеспечению катастрофоустойчивости и безопасности блочных устройств (RBD) в кластере Ceph. Рассматриваются клиентское кэширование и Persistent Write Log (PWL), QoS, страйпинг, выбор клиента (krbd/librbd/rbd-nbd), тюнинг памяти, совместимость версий ядра, живая миграция образов, асинхронная репликация (RBD Mirroring) с процедурами failover/failback, клиентское шифрование, продвинутая настройка Ceph CSI, мониторинг и бенчмаркинг, а также типовые неисправности и лучшие практики эксплуатации.

Предполагается, что читатель знаком с основами RBD: созданием образов, снапшотами и клонами (см. «[Определения и фундаментальные концепции](./definitions_and_concepts.md)» и «[Управление образами RBD](./image_management.md)»), а также с подготовкой клиентской среды (см. «[Установка и настройка клиента](./installation_and_setup.md)»).

## Определения

**RBD Mirroring** — механизм асинхронной репликации образов между территориально распределенными кластерами Ceph для обеспечения катастрофоустойчивости (Disaster Recovery). Репликация выполняется на уровне «мастер»–«реплика» (primary/non-primary): образ-реплика доступен только для чтения и не может быть изменен стандартными клиентами.

**Primary / Non-primary образ** — признак принадлежности образа одной из сторон репликации. Primary-образ принимает запись; non-primary-образ является копией и доступен только на чтение. Признак назначается **для каждого образа** в отдельности, поэтому два кластера могут делить нагрузку чтения между собой и поэтапно выполнять failover/failback.

**QoS (Quality of Service)** — набор параметров для гранулярного ограничения пропускной способности (BPS) и количества операций ввода-вывода (IOPS), включая поддержку всплесков (Bursting). Параметры применяются динамически, без перезапуска приложений, и действуют на уровне отдельного образа.

**Persistent Cache (Persistent Write Log Cache, PWL)** — технология кэширования на стороне клиента с использованием быстрых локальных накопителей (SSD/NVMe или PMEM), позволяющая радикально снизить задержки на запись. В отличие от обычного кэша в оперативной памяти, PWL сохраняет журнал транзакций на локальном устройстве и переживает сбой клиентского процесса.

**RWL (Replica Write Log)** — режим кэша PWL, использующий в качестве устройства кэша энергонезависимую память (PMEM/NVM). Название отражает изначально задуманную «реплицируемую» модель журнала; в текущих версиях поддерживается только локальный кэш, репликация между узлами находится в разработке. Требует библиотеки `libpmem` (PMDK) и файловой системы с поддержкой DAX.

**Живая миграция (Live Migration)** — процесс перемещения данных образа между пулами (например, с HDD на SSD), а также изменения «неизменяемого» on-disk-макета (размер объекта, страйпинг) без остановки работы клиента. Выполняется в три стадии: `prepare` → `execute` → `commit`/`abort`.

**LUKS (Linux Unified Key Setup)** — стандарт шифрования блочных устройств, поддерживаемый RBD. Заголовок LUKS хранит зашифрованный ключ шифрования, защищенный пользовательской секретной фразой (passphrase), которая никогда не сохраняется в кластере.

---

## Базовые концепции

### Оптимизация производительности

#### 1. Клиентское кэширование (librbd cache)

librbd не может использовать page cache ядра (он работает в пользовательском пространстве), поэтому включает собственный кэш в оперативной памяти клиента (KVM/QEMU, CSI-узел, rbd-nbd). Кэш строит по алгоритму LRU и умеет «склеивать» смежные запросы для повышения пропускной способности.

*   **Write-back**: Данные считаются записанными после попадания в кэш клиента. Максимальная скорость, риск потери данных при сбое узла.
*   **Write-through**: Запись подтверждается только после фиксации в кластере. Безопасно, но медленно.
*   **Write-around**: Компромиссный режим по умолчанию — запись подтверждается сразу же (как в write-back), но кэш **не используется для чтения**. Более быстр для производительных нагрузок на запись.
*   **Safe mode**: `rbd_cache_writethrough_until_flush` — начинает в режиме write-through и переходит в write-back только после получения первой команды flush от приложения (сигнал о том, что ОС умеет управлять целостностью). Включен по умолчанию и безопасен даже для гостевых ОС, которые не шлют flush.

Кэш корректен с точки зрения целостности при условии, что гостевая ОС корректно шлет flush/barrier (Linux >= 2.6.32). Если образ используют **одновременно несколько клиентов** (например, кластерная ФС GFS2/OCFS2 поверх RBD), запись через кэш приведет к рассинхронизации — в таких сценариях кэш необходимо отключить.

Основные параметры (задаются в секции `[client]` конфигурации, в центральном конфиг-сторе или через `rbd config`):

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `rbd_cache` | `true` | Включение/отключение кэша librbd. |
| `rbd_cache_policy` | `writearound` | Политика записи: `writethrough`, `writeback`, `writearound`. |
| `rbd_cache_size` | `32Mi` | Размер кэша на один образ (per-volume). |
| `rbd_cache_max_dirty` | `24Mi` | Порог «грязных» данных, при достижении которого начинается сброс в кластер. `0` = принудительный write-through. |
| `rbd_cache_target_dirty` | `16Mi` | Целевой объем dirty-данных, при котором сброс активизируется (запись при этом не блокируется). |
| `rbd_cache_max_dirty_age` | `1.0` | Возраст dirty-данных (в секундах), после которого начинается writeback. |
| `rbd_cache_writethrough_until_flush` | `true` | Старт в write-through до первого flush (Safe mode). |

Примеры применения через `rbd config` (переопределяют значения из `[client]`):

```bash
# Глобально для всех клиентов
rbd config global set rbd_cache_policy writeback
rbd config global set rbd_cache_size 128M

# Для конкретного образа
rbd config image set kube/my-image rbd_cache_size 256M
rbd config image get kube/my-image rbd_cache_size
# → rbd_cache_size: 256M

# Полный список активных параметров образа
rbd config image list kube/my-image
```

Ограничение: параметры librbd-кэша применяются только к клиентам `librbd` (QEMU/KVM, CSI, rbd-nbd). Образы, подключенные через модуль ядра `krbd`, используют обычный page cache Linux и управляются стандартными средствами ОС (readahead, `posix_fadvise` и т.п.).

#### 2. Persistent Write Log (PWL)

Современная альтернатива обычному кэшу. Использует SSD или PMEM на узле клиента для хранения журнала транзакций. Обеспечивает производительность write-back с надежностью, близкой к локальному диску. PWL выполняет упорядоченную запись в журнал с внутренними контрольными точками: данные, подтвержденные и сброшенные (flush), всегда консистентны, даже если кэш будет полностью утерян при сбое клиента.

**Режимы устройства кэша:**

*   `ssd` — кэш на обычном SSD/NVMe-накопителе. Не требует специального оборудования, подходит для большинства случаев.
*   `rwl` — кэш на энергонезависимой памяти (PMEM). Требует `libpmem` (PMDK) и файловой системы с включенным DAX; иначе теряется преимущество в задержке. Недоступен на архитектуре s390x.

**Режимы подтверждения записи:**

*   *Persistent-on-write*: запись подтверждается только после попадания в устройство кэша и переживает перезапуск/сбой клиента.
*   *Persistent-on-flush*: запись подтверждается сразу после использования буфера вызывающего, но гарантии пережить сбой нет до получения flush. Данные фиксируются в кэш при получении flush-запроса.

**Параметры включения** (минимальный размер кэша на образ — 1 GiB):

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `rbd_plugins` | пусто | Плагин librbd `pwl_cache` — обязателен для загрузки механизма кэша. |
| `rbd_persistent_cache_mode` | `disabled` | Режим: `ssd`, `rwl` или `disabled`. |
| `rbd_persistent_cache_path` | `/tmp` | Каталог для файлов кэша. Для `rwl` обязателен DAX-раздел. |
| `rbd_persistent_cache_size` | `1G` | Размер кэша на образ, минимум 1 GiB. |

`rbd_plugins` задается в секции `[client]` конфигурации (или централизованно); режим, путь и размер — через `rbd config image/pool set`, что позволяет включать/выключать кэш динамически. Кэш требует эксклюзивной записи в образ (совместим с типичной работой CSI, где активен только один писатель) и поддерживается только клиентами `librbd`; `krbd` PWL не поддерживает.

Управление состоянием кэша:

```bash
# Сброс всех dirty-данных из кэша в кластер (например, перед остановкой клиента)
rbd persistent-cache flush kube/my-image

# Полная невалидация (очистка) кэша — обязательна перед деактивацией режима
rbd persistent-cache invalidate kube/my-image
```

#### 3. Стрипинг (Striping v2)

Разделение данных образа на части для параллельной записи на разные OSD.

*   `stripe_unit`: Размер минимального блока данных.
*   `stripe_count`: Количество объектов, по которым распределяются данные перед переходом к следующей итерации. Оптимально для Big Data и потокового I/O.

По умолчанию образ использует «простое» разбиение: `stripe_unit` равен размеру объекта (по умолчанию 4 МиБ), а `stripe_count = 1`, т.е. весь объект записывается единым блоком. Режим «fancy striping» (`stripe_unit` меньше размера объекта) заставляет конфигурации писать последовательный поток чередующимися фрагментами на несколько объектов одного «страйпа», что особенно полезно для **однопоточных** нагрузок с крупными транзакциями: повышается параллелизм I/O на одноуровневом клиенте, большие блоки распределяются между несколькими OSD.

Применение страйпинга сопряжено с компромиссами: фрагментация данных на большее число объектов увеличивает количество метаданных операций, усложняет и удорожает обработку снапшотов и flatten-операций. Страйпинг требует формата 2 образа (используется по умолчанию) и устанавливается **только при создании образа или через живую миграцию** — на существующем образе макет изменить динамически нельзя.

```bash
# Создание образа с "fancy striping": фрагменты по 256 КиБ на 8 объектов
rbd create --size 10240 --pool kube --image-format 2 \
  --stripe-unit 256K --stripe-count 8 my-striped

# Проверка выбранного макета
rbd info kube/my-striped
# → rbd image 'my-striped':
#      size 10 GiB ...
#      order 22 (4 MiB objects) ...
#      stripe unit: 256 KiB
#      stripe count: 8
```

#### 4. Размер объекта (Object Size)

Размер объекта (`order`) — степень двойки, определяющая размер базового объекта RADOS (по умолчанию 4 МиБ). Выбор размера объекта — это компромисс между параллелизмом и накладными расходами:

*   **Крупные объекты** (8–64 МиБ): меньше объектов и меньше накладных расходов на metadata; выгодны для крупных последовательных чтений/записей, но усиливают read amplification при случайном мелкоблочном I/O.
*   **Мелкие объекты** (1–2 МиБ): лучше для нагрузок с мелкоблочным случайным I/O и для эффективного использования fast-diff/«дырок», но создают больше объектов и metadata-операций.

Поскольку макет фиксируется при создании, изменяется он только миграцией:

```bash
rbd migration prepare --object-size 1M kube/my-image
rbd migration execute kube/my-image
rbd migration commit kube/my-image
```

#### 5. Выбор клиента: krbd, librbd и rbd-nbd

Ceph предоставляет три основных способа доступа к образам RBD, каждый из которых имеет компромиссы производительности и функциональности:

| Клиент | Уровень | Поддержка кэша | Поддержка шифрования | ПоддержкаPW | QoS | Примечание |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **krbd** | Модуль ядра Linux | Page cache ядра | Ядро 6.1+ | Нет | Нет | Базовый драйвер, максимальная совместимость |
| **librbd** (QEMU/KVM) | Пользовательское пространство | `rbd_cache` + PWL | Да | Да | Да | Основной драйвер для виртуализации |
| **librbd** (Ceph CSI) | Пользовательское пространство | `rbd_cache` + PWL | Да | Да | Да | Драйвер для Kubernetes PVC |
| **rbd-nbd** | Пользовательское пространство (NBD) | `rbd_cache` + PWL | Да | Да | Да | Альтернатива krbd для полного набора функций |

**krbd** — модуль ядра, который проще всего в настройке, но ограничен в функциональности: не поддерживает клиентский кэш librbd, PWL, QoS и шифрование (до ядра 6.1). Используется при маппинге через `rbd map` и для не-виртуализационных сценариев (монтирование ФС, ручное управление дисками).

**rbd-nbd** — пользовательский демон, использующий протокол NBD (Network Block Device) для предоставления образа как блочного устройства. Работает поверх `librbd`, поэтому наследует все его возможности: кэширование, PWL, QoS, шифрование. Преимущество перед krbd — полная поддержка функций независимо от версии ядра. Недостаток — дополнительный процесс в пользовательском пространстве и накладные расходы перекодирования между NBD и ядром.

```bash
# Маппинг через rbd-nbd (вместо krbd)
sudo rbd device map -t nbd kube/my-image

# Проверка типа устройства
rbd showmapped
# → IMAGE          SOURCE   DEVICE      POOL  ...
#    my-image       rbd      /dev/nbd0   kube  ...
```

**Рекомендация по выбору:**
*   Виртуализация (KVM/QEMU): `librbd` (нативная интеграция через QEMU).
*   Kubernetes (Ceph CSI): `librbd` (по умолчанию).
*   Нужно шифрование или PWL на старом ядре (ниже 6.1): `rbd-nbd`.
*   Простое монтирование ФС без требований к производительности: `krbd`.

#### 6. Тюнинг памяти librbd

Кэш librbd (`rbd_cache_size`) потребляет оперативную память клиента. В средах с большим количеством образов на одном узле (KVM-хост с десятками VM, Kubernetes-узел с многими Pod) суммарное потребление может оказаться значительным:

*   `rbd_cache_size` задается **на каждый образ** (per-volume). По умолчанию 32 МиБ.
*   `rbd_cache_max_dirty` — максимальный объем «грязных» данных в кэше (по умолчанию 24 МиБ). Потребляет основную часть памяти.
*   Для 100 образов с кэшем по 32 МиБ: 100 x 32 = 3.2 GiB только для кэша (плюс overhead структур данных).

Стратегии управления памятью:

1.  **Снижение размера кэша** для образов с низкой нагрузкой:

```bash
# Уменьшить кэш для всех образов в пуле (через pool-level default)
rbd config pool set kube rbd_cache_size 16M
rbd config pool set kube rbd_cache_max_dirty 12M
```

2.  **Отключение кэша** для образов, где приоритетна экономия памяти:

```bash
rbd config image set kube/idle-image rbd_cache false
```

3.  **Мониторинг потребления** — для каждого процесса-клиента суммарный размер кэша равен `rbd_cache_size * количество_открытых_образов`. Используйте `ceph daemon <daemon> dump_mempool` (для OSD/MGR) или внешние инструменты мониторинга памяти.

4.  Для **krbd** (модуль ядра) кэш librbd не используется — управление page cache ОС выполняется через `posix_fadvise`, `vmtouch` или стандартные/sysctl-параметры ядра (`vm.dirty_ratio`, `vm.dirty_background_ratio`).

### Совместимость версий ядра и функций RBD

Функции образов (`image-features`) требуют определенных минимальных версий ядра Linux для корректной работы через `krbd`. Несоответствие приводит к отказу при маппинге:

| Функция | Минимальное ядро (krbd) | Примечание |
| :--- | :--- | :--- |
| `layering` | 2.6.32 | Базовая поддержка копирования при записи |
| `exclusive-lock` | 3.10 | Блокировка для одно-писателя |
| `object-map` | 4.9 | Карта занятых объектов для ускорения `ls`/`du`/`resize` |
| `fast-diff` | 4.9 | Вычисление разницы между снапшотами |
| `deep-flatten` | 4.9 | Удаление снапшотов с дочерними клонами |
| `journaling` | 4.17 | Журналирование для `rbd-mirror` |
| `operations` | 4.17 | Фоновые операции (flatten, resize, etc.) |
| `data-pool` | 4.16 | Раздельные пулы данных (erasure coding) |
| `encryption` | 6.1 | Клиентское шифрование LUKS через krbd |

**Важно:** если `krbd` не поддерживает нужную функцию, используйте `rbd-nbd` или `librbd` (QEMU/CSI) — они работают в пользовательском пространстве и не зависят от версии ядра.

```bash
# Проверка текущей версии ядра
uname -r

# Проверка версии модуля ядра rbd
modinfo rbd | grep version

# Проверка включенных функций образа
rbd info kube/my-image | grep features
# → features: layering,exclusive-lock,object-map,fast-diff,deep-flatten
```

### Exclusive-lock и мульти-райтер сценарии

Функция `exclusive-lock` гарантирует, что в один момент времени только один клиент имеет право на запись в образ. Это критически важно для предотвращения рассинхронизации данных, но создает ограничения в кластерных сценариях.

**Одиночный писатель (стандартный случай):**

*   VM или Pod монтирует образ — exclusive-lock блокирует запись другим клиентам.
*   Второй клиент может получить образ в режиме «только чтение», если явно запрошен shared lock.

**Кластерные ФС поверх RBD (GFS2, OCFS2):**

*   Одновременный доступ нескольких узлов к одному образу возможен только через кластерную файловую систему с распределенной блокировкой (DLM).
*   В таком режиме `exclusive-lock` должен быть **отключен** или сконфигурирован в режиме shared lock, иначе вторичные узлы не смогут писать.
*   Кэш `rbd_cache` в write-back режиме **обязательно отключить** — иначе рассинхронизация данных неизбежна.

```bash
# Отключение exclusive-lock (только если используется кластерная ФС с DLM)
rbd feature disable kube/shared-disk exclusive-lock

# Проверка статуса блокировки
rbd lock list kube/my-image
```

**Разрешенные сценарии параллельного доступа:**

*   Один писатель + несколько читателей (shared lock).
*   Кластерная ФС (GFS2/OCFS2) с DLM и отключенным `exclusive-lock`.
*   Read-only PVC в Kubernetes (множественные поды читают один и тот же volume).

**Определение владельца блокировки:**

```bash
# Кто держит exclusive-lock
rbd status kube/my-image
# → Watchers:
#    10.0.0.5:0 client.4132 ... (exclusive)

# Принудительный сброс блокировки (только при полной уверенности, что данные не пишутся)
rbd lock remove kube/my-image "locker-id" client.id
```

### Тонкое провизионирование и освобождение пространства

RBD использует тонкое провизионирование по умолчанию: образ резервирует место в RADOS только при фактической записи данных. Однако удаление данных на уровне файловой системы (внутри образа) не автоматически освобождает физическое пространство в Ceph — для этого необходим механизм **discard/TRIM**.

**Как это работает:**

1.  Гостевая ОС удаляет файл и (при включенном TRIM) отправляет команду DISCARD на блочное устройство.
2.  Ядро Linux (krbd или rbd-nbd) передает команду в Ceph RADOS.
3.  Ceph освобождает соответствующие объекты RADOS, уменьшая использование пространства в пуле.

**Настройка TRIM:**

*   **На уровне ФС:** опция монтирования `discard` (непрерывный) или периодический `fstrim` (рекомендуется для production).
*   **На уровне krbd:** TRIM поддерживается автоматически при наличии ядра 4.12+.
*   **На уровне пула:** включите `rbd_discard` для пула (по умолчанию включен):

```bash
# Проверка/включение дискарда на уровне пула
ceph osd pool get kube rbd_discard
# → rbd_discard: true

# Включение (если отключен)
ceph osd pool set kube rbd_discard true
```

**Важно для зашифрованных образов:** TRIM раскрывает паттерн заполнения диска (какие блоки пустые), что может быть проблематично с точки зрения безопасности. Для большинства серверных сценариев это приемлемый компромисс.

**Мониторинг использования пространства:**

```bash
# Фактическое использование данных (включая дедупликацию/сжатие)
rbd du kube/my-image
# → NAME     PROVISIONED  USED
#    my-image  10 GiB      3.2 GiB

# Использование на уровне пула
ceph df detail
```

### Продвинутая настройка Ceph CSI

При использовании RBD через Ceph CSI в Kubernetes доступны дополнительные параметры StorageClass, расширяющие возможности по умолчанию:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-encrypted
provisioner: rbd.csi.ceph.com
parameters:
  # Подключение к кластеру
  clusterID: <fsid-кластера>
  pool: kube

  # Тип образа (block по умолчанию, можно указать "fs" для CephFS)
  csi.storage.k8s.io/provisioner-secret-name: csi-rbd-secret
  csi.storage.k8s.io/node-stage-secret-name: csi-rbd-secret
  csi.storage.k8s.io/provisioner-secret-namespace: default
  csi.storage.k8s.io/node-stage-secret-namespace: default

  # Расширенные опции
  imageFeatures: layering,exclusive-lock,object-map,fast-diff,deep-flatten
  encrypted: "true"
  encryptionKMSID: "vault-key"
  csi.storage.k8s.io/fstype: xfs
  mapOptions: "krbd"  # или "rbd-nbd" для полного набора функций

  # Тонкое провизионирование ( thinProvisioned по умолчанию true)
  thinProvisioned: "true"

reclaimPolicy: Delete
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

**Ключевые параметры:**

*   `imageFeatures` — задает набор функций образа. Для snapshot-based mirroring необходимы `exclusive-lock` и `fast-diff`.
*   `mapOptions` — выбор клиента: `krbd` (по умолчанию, модуль ядра) или `rbd-nbd` (пользовательский, больше возможностей).
*   `encrypted: "true"` — автоматическое шифрование LUKS2 при создании PVC. Требует настроенного KMS (HashiCorp Vault, кейтос).
*   `allowVolumeExpansion: true` — разрешает расширение PVC без пересоздания.
*   `thinProvisioned: "true"` — тонкое провизионирование (по умолчанию).

**Расширение существующего PVC:**

```bash
# Увеличение PVC с 10Gi до 50Gi
kubectl patch pvc my-pvc -p '{"spec":{"resources":{"requests":{"storage":"50Gi"}}}}'

# Проверка прогресса
kubectl describe pvc my-pvc
# → Conditions:
#    Type:      Resizing
#    Status:    True
```

**Read-only PVC (для бэкапов и анализа):**

```bash
# Создание Pod с read-only mount существующего PVC
kubectl run rbd-reader --image=busybox --rm -it --restart=Never \
  --overrides='{"spec":{"containers":[{"name":"rbd-reader","image":"busybox","command":["sh"],"args":["-c","sleep 3600"],"volumeMounts":[{"name":"data","mountPath":"/data","readOnly":true}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"my-pvc","readOnly":true}}]}}'
```

### Отказоустойчивость: RBD Mirroring

Демон `rbd-mirror` обеспечивает репликацию на уровне отдельных образов или целых пулов:

*   **Journal-based (Журналирование)**: Каждый запрос на запись фиксируется в журнале и воспроизводится на удаленном кластере. Гарантирует строгую последовательность (Consistency) и минимальный RPO (копия всегда актуальна), но каждая запись приводит к **двум операциям записи** в кластер — латентность записи почти удваивается.
*   **Snapshot-based (На базе снапшотов)**: Репликация происходит по расписанию через дифференциальную передачу снапшотов. Менее ресурсозатратно, рекомендуется для большинства современных инсталляций (доступно с версии Octopus). RPO определяется частотой снапшотов; частично переданная дельта при failover откатывается, поэтому данные на момент переключения всегда консистентны.

Репликация может быть **однонаправленной** (односторонним потоком — `rbd-mirror` запущен только на вторичном кластере) или **двунаправленной** (`rbd-mirror` на обоих кластерах; образы можно двигать по желанию в обе стороны). Требования:

*   пул на обоих кластерах должен называться **одинаково**;
*   каждый демон `rbd-mirror` должен иметь сетевую доступность до мониторов и OSD **обоих** кластеров одновременно;
*   между ЦОДами должен быть достаточный канал, чтобы успевать передавать дельты в рамках RPO;
*   для snapshot-based режима на образе должны быть включены функции `exclusive-lock` и `fast-diff` (последняя ускоряет вычисление измененных блоков);
*   для journal-based режима необходима функция `journaling` (зависит от `exclusive-lock`).

**Статусы образа** (проверяются `rbd mirror image status` / `rbd mirror pool status`):

| Статус | Значение |
| :--- | :--- |
| `up+stopped` | Демон запущен, образ является **primary** на этом кластере — репликация к нему не выполняется. |
| `up+replaying` | Демон запущен, образ получает данные от primary-образа (норма для реплики). |
| `up+syncing` | Выполняется начальная синхронизация или принудительный resync. |
| `down` | Демон не обрабатывал образ дольше заданного порога (обычно проблемы сети, кворума или нехватка исключительной блокировки). |
| `error` | Образ не может быть реплицирован (например, повреждение или рассинхронизация). |

**Ограничение (важно для планирования failover):** перед переносом primary-статуса на резервный кластер полная дельта между снапшотами должна быть передана. Координацию «остановить запись → demote → promote» RBD не автоматизирует — ей занимается внешний оркестратор (виртуализация, приложение, оператор).

### Безопасность и шифрование

Шифрование RBD выполняется **исключительно на стороне клиента** (End-to-End Encryption). Кластер Ceph видит только зашифрованные блоки.

*   **Стандарты**: LUKS1, LUKS2.
*   **Реализация**: Через Ceph CSI (автоматически при создании PVC) или вручную через `rbd encryption format`.

Формат LUKS полностью совместим со спецификацией, поэтому зашифрованные образы можно монтировать внешними инструментами (dm-crypt, QEMU). Поддерживаются алгоритмы AES-128 и AES-256 (по умолчанию AES-256) в режиме `xts-plain64`. Операция форматирования записывает в начало образа заголовок LUKS с одним keyslot, защищающим случайный ключ шифрования. Ключ защищен файлом секретной фразы (passphrase-file), который **никогда не сохраняется в кластере** — потеря файла означает полную потерю данных.

Нюансы производительности и совместимости:

*   В LUKS1 сектор (минимальная единица шифрования) фиксирован на 512 байт; в LUKS2 по умолчанию используется сектор 4 КиБ. Записи, не выровненные по сектору, вызывают каскад read-modify-write с ощутимой задержкой — для смешанных мелкоблочных нагрузок шифрование может сильно проигрывать.
*   Маппинг зашифрованного образа через `krbd` требует ядра **6.1+**; клиенты `librbd` (QEMU, rbd-nbd) работают без ограничений по ядру.
*   Для **клона**, созданного из зашифрованного снапшота, при маппинге нужно передать формат/файл-пароль сначала для клона, затем для каждого явно зашифрованного родителя (по иерархии образа).
*   Добавление/удаление passphrase командой `rbd` не поддерживается — для ротации используйте `cryptsetup` на «сыром» устройстве.

Для снятия «дыры» в шифровании (быстрый поиск свободных блоков) целесообразно использовать `discard`/TRIM на клиенте: в Ceph для зашифрованных образов освобождение пространства выполняется через дискард.

---

## Практические сценарии

### 1. Тонкая настройка QoS (Лимиты и Bursting)

Параметры QoS можно изменять "на лету" без перезагрузки приложений. Поддерживаются отдельные лимиты для чтения, записи и общий, а также мгновенные «всплески» (burst), разрешающие превышение лимита на короткий период.

```bash
# Ограничение IOPS (800) и установка Burst (до 2000 IOPS на 60 секунд)
rbd config image set kube/my-image rbd_qos_iops_limit 800
rbd config image set kube/my-image rbd_qos_iops_burst 2000
rbd config image set kube/my-image rbd_qos_iops_burst_seconds 60

# Ограничение скорости записи (50 MiB/s)
rbd config image set kube/my-image rbd_qos_write_bps_limit 52428800

# Раздельные лимиты на чтение
rbd config image set kube/my-image rbd_qos_read_bps_limit 104857600   # 100 MiB/s
rbd config image set kube/my-image rbd_qos_read_iops_limit 2000
```

Полный набор параметров (для каждого типа I/O есть своя пара `_limit`/`_burst`/`_burst_seconds`):

| Группа | Параметры |
| :--- | :--- |
| Общий BPS | `rbd_qos_bps_limit`, `rbd_qos_bps_burst`, `rbd_qos_bps_burst_seconds` |
| BPS чтения | `rbd_qos_read_bps_limit`, `rbd_qos_read_bps_burst`, `rbd_qos_read_bps_burst_seconds` |
| BPS записи | `rbd_qos_write_bps_limit`, `rbd_qos_write_bps_burst`, `rbd_qos_write_bps_burst_seconds` |
| Общий IOPS | `rbd_qos_iops_limit`, `rbd_qos_iops_burst`, `rbd_qos_iops_burst_seconds` |
| IOPS чтения | `rbd_qos_read_iops_limit`, `rbd_qos_read_iops_burst`, `rbd_qos_read_iops_burst_seconds` |
| IOPS записи | `rbd_qos_write_iops_limit`, `rbd_qos_write_iops_burst`, `rbd_qos_write_iops_burst_seconds` |

Применение значений и проверка:

```bash
# Определение значений по умолчанию для пула (наследуются всеми образами)
rbd config pool set kube rbd_qos_iops_limit 1000

# Проверка фактических значений образа
rbd config image get kube/my-image rbd_qos_iops_limit
rbd config image get kube/my-image rbd_qos_write_bps_limit

# Сброс ограничения (возврат к значению пула/по умолчанию)
rbd config image remove kube/my-image rbd_qos_iops_limit
```

Ограничения применяются на клиентах `librbd` (QEMU/CSI). На клиентах `krbd` параметры `rbd_qos_*` не действуют — там используйте лимиты на уровне ОС (например, `ionice`, `systemd`/cgroup `io.max`).

### 2. Настройка Persistent Cache (SSD)

Для включения кэширования на локальном SSD узла (например, в Kubernetes):

```bash
# 1) Один раз на клиенте: активировать плагин pwl_cache (секция [client] ceph.conf
#    или центральный конфиг-стор). Пример для ceph.conf:
#    [client]
#    rbd_plugins = pwl_cache

# 2) Включение кэша для конкретного образа (динамически)
rbd config image set kube/my-image rbd_persistent_cache_mode ssd
rbd config image set kube/my-image rbd_persistent_cache_path /var/lib/ceph/cache/
rbd config image set kube/my-image rbd_persistent_cache_size 10Gi

# 3) Проверка активных параметров
rbd config image list kube/my-image | grep persistent

# 4) Перед плановой остановкой клиента — сброс dirty-данных в кластер
rbd persistent-cache flush kube/my-image

# 5) Деактивация кэша (удаление файла кэша)
rbd persistent-cache invalidate kube/my-image
rbd config image set kube/my-image rbd_persistent_cache_mode disabled
```

Для кластеров Kubernetes через Ceph CSI параметры кэша задаются в StorageClass:

```yaml
# StorageClass (ceph-csi, драйвер rbd)
parameters:
  csi.storage.k8s.io/controller-publish-secret-name: ceph-secret
  csi.storage.k8s.io/node-stage-secret-name: ceph-secret
  persistentCacheMode: ssd
  persistentCachePath: /var/lib/ceph/cache/
  persistentCacheSize: "10Gi"
```

Требования к узлу: для `ssd`-режима достаточно обычной файловой системы с запасом свободного места; для `rwl`-режима необходим PMEM и файловая система с DAX. Размер кэша на образ не может быть меньше 1 GiB.

### 3. Живая миграция между пулами (HDD -> SSD)

```bash
# Начало миграции (подготовка): исходный образ становится read-only для всех
# писателей, создается целевой образ в новом пуле
rbd migration prepare kube/my-image ssd-pool/my-image

# Выполнение копирования (клиент продолжает работу с новым образом)
rbd migration execute ssd-pool/my-image
# → Image migration: 100% complete...done.

# Контроль состояния миграции
rbd status ssd-pool/my-image
# → Migration:
#      source: rbd/my-image (5e2cba2f62e)
#      destination: rbd/ssd-pool/my-image (5e2ed95ed806)
#      state: executed

# Фиксация миграции (удаление исходного образа)
rbd migration commit ssd-pool/my-image
# → Commit image migration: 100% complete...done.
```

Миграция с изменением «неизменяемого» макета (размер объекта, страйпинг) на том же пуле — `dest` можно опустить, имя образа сохраняется:

```bash
# Изменение объектного размера и страйпинга "на лету"
rbd migration prepare --object-size 1M --stripe-unit 256K --stripe-count 8 kube/my-image
rbd migration execute kube/my-image
rbd migration commit kube/my-image

# Проверка нового макета
rbd info kube/my-image
```

**Откат** (до `commit`): прерывание миграции удаляет целевой образ и восстанавливает доступ к исходному:

```bash
rbd migration abort kube/my-image
# → Abort image migration: 100% complete...done.
```

**Важные правила:**

*   Перед `prepare` (в пределах одного кластера) доступ клиентов с запись/чтением к исходному образу должен быть остановлен — иначе подготовка завершится ошибкой. После `prepare` клиенты продолжают работу, используя **целевое** имя образа; подключение к исходному имени больше не работает.
*   `commit` окончательно удаляет исходный образ; `abort` — удаляет целевой образ со всеми данными, записанными в него (включая новые данные клиентов).
*   Для импорта данных извне кластера (`--import-only` + JSON `source-spec`) поддерживаются форматы `native` (образ другого кластера Ceph), `qcow` и `raw`, а также потоки `file`, `http`, `s3` и `nbd`:

```bash
# Импорт из локального raw-файла как живая миграция
cat > spec.json <<'EOF'
{ "type": "raw", "stream": { "type": "file", "file_path": "/srv/images/vm.raw" } }
EOF
rbd migration prepare --import-only --source-spec-path spec.json kube/imported
rbd migration execute kube/imported
rbd migration commit kube/imported
```

### 4. Настройка RBD Mirroring (Snapshot-based)

Полная процедура настройки двухплощадочной (two-site) репликации. Пример: кластеры `site-a` (основной) и `site-b` (резервный), общий пул `image-pool`.

**Шаг 1. Предварительные требования.**

*   Пул с одинаковым именем создан на обоих кластерах.
*   Демоны `rbd-mirror` развернуты (для двунаправленной репликации — на обоих кластерах):

```bash
# Через cephadm: разместить 2 демона rbd-mirror на узлах кластера
ceph orch apply rbd-mirror 2
ceph orch ps --daemon-type rbd-mirror
```

*   На образах, которые будут реплицироваться, включены функции `exclusive-lock` и `fast-diff` (рекомендуемый набор по умолчанию при создании через CSI).
*   Модуль mgr `rbd_support` активен (в cephadm включен по умолчанию) — требуется для расписаний снапшотов:

```bash
ceph mgr module enable rbd_support
```

**Шаг 2. Включение зеркалирования пула (на обоих кластерах).** Режим `image` — реплицируются только явно включенные образы; режим `pool` — все образы пула с включенным journaling.

```bash
rbd mirror pool enable --site-name site-a image-pool image
rbd mirror pool enable --site-name site-b image-pool image
```

**Шаг 3. Регистрация пиров (peer bootstrap).** На `site-a` создается токен, который импортируется на `site-b`:

```bash
# --- на site-a ---
rbd mirror pool peer bootstrap create --site-name site-a image-pool > peer-token

# --- на site-b ---
# --direction rx-tx — двунаправленная репликация (по умолчанию);
# rx-only — однонаправленная
rbd mirror pool peer bootstrap import --site-name site-b --direction rx-tx image-pool peer-token

# Проверка регистрации пира на site-b
rbd mirror pool info image-pool --all
```

**Шаг 4. Включение зеркалирования образа (только на primary-кластере).** После включения автоматически создается первый mirror-snapshot.

```bash
rbd mirror image enable image-pool/my-image snapshot
```

**Шаг 5. Расписание снапшотов** (определяет целевой RPO). Интервал задается в минутах (`m`), часах (`h`) или днях (`d`), с опциональным временем старта по ISO 8601:

```bash
# Резервная копия каждого 10 минут для образа в пуле
rbd mirror snapshot schedule add --pool image-pool 10m

# Список расписаний (на уровне пула рекурсивно)
rbd mirror snapshot schedule ls --pool image-pool --recursive

# Просмотр ближайших созданий снапшотов
rbd mirror snapshot schedule status
```

**Шаг 6. Проверка статуса зеркалирования.**

```bash
# Статус пула (сводка по всем образам)
rbd mirror pool status image-pool

# Статус конкретного образа на реплике (site-b)
rbd mirror image status image-pool/my-image
# → my-image:
#      global_id:   <uuid>
#      state:       up+replaying
#      description: replaying, {...}
#      last_update: 2026-08-29 14:00:00
```

Состояние `up+replaying` на резервном кластере означает, что репликация работает нормально.

**Failover (плановый перенос primary на site-b):**

```bash
# 1) Остановить запись приложений на старом primary и дать доехать дельте
rbd mirror image status image-pool/my-image        # на site-a: дождаться передачи данных

# 2) Демотировать образ на site-a (запретить запись, создать demote-snapshot)
rbd mirror image demote image-pool/my-image
rbd mirror image status image-pool/my-image        # → state: up+stopped

# 3) На site-b выполнить промоушн в primary
rbd mirror image promote image-pool/my-image
rbd mirror image status image-pool/my-image        # → state: up+stopped (теперь это primary)

# 4) Разрешить запись приложениям на резервном кластере
```

**Failback** выполняется в обратном порядке: `demote` на site-b, `promote` на site-a и повторная синхронизация.

**Аварийный failover (site-a недоступен) и восстановление:**

```bash
# Принудительный промоушн — используется, когда demote нельзя передать пиру.
# Влечет split-brain (дельта между кластерами) до явного resync.
rbd mirror image promote --force image-pool/my-image

# После восстановления сети определить актуальный сайт (по last_update),
# на отстающем сайте выполнить demote и принудительный resync
rbd mirror image demote image-pool/my-image
rbd mirror image resync image-pool/my-image
```

**Важно:**

*   RBD предоставляет только инструменты упорядоченного failover; остановку записи и переключение приложений выполняет внешний координатор (Ceph Cluster Manager API, оркестратор виртуализации или оператор).
*   Для snapshot-based режима resync воспроизводит данные **до самого свежего mirror-snapshot**; чтобы синхронизировать «хвост», создайте новый снапшот на primary.
*   Двунаправленная репликация (`rx-tx`) официально поддерживается только между **двумя** площадками.

### 5. Шифрование образа через CLI

Форматировать образ в LUKS можно только при отсутствии активного маппинга; образ должен обладать функцией `exclusive-lock`.

```bash
# 1) Создание файла секретной фразы (без завершающего перевода строки!)
sudo mkdir -p /etc/ceph
printf '%s' 'correct horse battery staple' | sudo tee /etc/ceph/luks-pass >/dev/null
sudo chmod 600 /etc/ceph/luks-pass

# 2) Форматирование образа под LUKS2 (по умолчанию AES-256/xts-plain64)
rbd encryption format kube/my-image luks2 /etc/ceph/luks-pass
# → Security: LUKS2 formatting with AES-256 ...

# 3) Маппинг зашифрованного устройства
rbd device map -o encryption-format=luks2,encryption-passphrase-file=/etc/ceph/luks-pass kube/my-image
rbd showmapped
```

**Клоны из зашифрованных снапшотов.** При маппинге указываются форматы/файлы-пароли в порядке иерархии: сначала клон, затем родитель:

```bash
rbd clone kube/my-image@snap1 clone-pool/clone-image
rbd device map -t nbd -o \
  encryption-format=luks2,encryption-passphrase-file=/etc/ceph/clone-pass, \
  encryption-format=luks2,encryption-passphrase-file=/etc/ceph/luks-pass \
  clone-pool/clone-image
```

**Ротация passphrase.** Добавление/удаление ключей командами `rbd` не поддерживается — выполняется через `cryptsetup` на «сыром» (не расшифрованном) устройстве:

```bash
# Маппинг образа БЕЗ опций шифрования даст /dev, содержащий LUKS2-заголовок
rbd device map -t nbd kube/my-image
# (устройство появится как, например, /dev/nbd0)

# Добавить новый ключ, сохранив старый
sudo cryptsetup luksAddKey /dev/nbd0 --key-file /etc/ceph/luks-pass.new
# Удалить старый
sudo cryptsetup luksDump /dev/nbd0
sudo cryptsetup luksRemoveKey /dev/nbd0 --key-file /etc/ceph/luks-pass

# Вернуть маппинг на расшифрованный режим
rbd device unmap -t nbd kube/my-image
rbd device map -o encryption-format=luks2,encryption-passphrase-file=/etc/ceph/luks-pass.new kube/my-image
```

**Проверка и диагностика.** Информация о зашифрованном образе отображается в `rbd info`:

```bash
rbd info kube/my-image
# → rbd image 'my-image':
#      ...
#      encryption format: luks2 (key protected by passphrase)
```

При работе в Kubernetes шифрование выполняется автоматически драйвером Ceph CSI при создании PVC (параметры `encryptionKMSID`/`encryptionPassphraseID` в StorageClass или через локальный KMS). Подробнее — в официальном руководстве Ceph CSI (см. раздел «Ресурсы»).

**Восстановление доступа без исходного файла пароля невозможно** — храните passphrase-file в защищенном менеджере секретов и делайте резервную копию заголовка LUKS (`cryptsetup luksHeaderBackup`) отдельно от кластера.

---

## Мониторинг и бенчмаркинг производительности RBD

### Метрики для мониторинга

Ключевые метрики для контроля производительности RBD в продуктовой среде:

```bash
# Использование пространства в пуле (включая overhead)
ceph df detail --format json-pretty | jq '.pools[] | select(.name=="kube")'

# Статистика операций RBD на клиенте (через librbd)
rbd status kube/my-image

# Статус миграции (если выполняется)
rbd status kube/my-image | grep -A5 Migration

# Мониторинг целостности PG
ceph pg stat

# Задержки OSD (для выявления проблем с производительностью на уровне кластера)
ceph daemon osd.0 dump_historic_ops | jq '.ops | sort_by(.duration) | last'
```

**Метрики Prometheus (через mgr-модуль):**

```bash
# Включение метрик Ceph для Prometheus
ceph mgr module enable prometheus

# Основные метрики:
# ceph_osd_op_r_latency_sum / ceph_osd_op_r_latency_count — латентность чтения OSD
# ceph_osd_op_w_latency_sum / ceph_osd_op_w_latency_count — латентность записи OSD
# ceph_pool_objects — количество объектов в пуле
# ceph_pool_bytes_used — использование пространства
```

### Бенчмаркинг с fio (рабочие сценарии)

Для точного измерения влияния оптимизаций используйте `fio` с движком `rbd` (прямое тестирование через librbd, без искажений уровня ФС):

```bash
# Тест случайного чтения 4K (OLTP-нагрузка) через RBD
fio --name=randread-rbd --ioengine=rbd --pool=kube --rbdname=my-image \
    --rw=randread --bs=4k --size=4G --iodepth=64 --numjobs=4 \
    --runtime=120 --time_based --group_reporting

# Тест последовательной записи 1M (потоковая нагрузка)
fio --name=seqwrite-rbd --ioengine=rbd --pool=kube --rbdname=my-image \
    --rw=write --bs=1m --size=10G --iodepth=16 --numjobs=1 \
    --runtime=120 --time_based --group_reporting

# Тест смешанной нагрузки (70% чтение / 30% запись, 8K блок — типичный паттерн СУБД)
fio --name=mixed-rbd --ioengine=rbd --pool=kube --rbdname=my-image \
    --rw=randrw --rwmixread=70 --bs=8k --size=4G --iodepth=32 --numjobs=4 \
    --runtime=120 --time_based --group_reporting
```

**Сравнение производительности клиентов:**

```bash
# Тест через krbd (модуль ядра)
sudo rbd map kube/perf-test
fio --name=krbd-test --filename=/dev/rbd0 --ioengine=libaio --direct=1 \
    --rw=randread --bs=4k --iodepth=64 --size=4G --runtime=60
sudo rbd unmap kube/perf-test

# Тест через rbd-nbd
sudo rbd device map -t nbd kube/perf-test
fio --name=nbd-test --filename=/dev/nbd0 --ioengine=libaio --direct=1 \
    --rw=randread --bs=4k --iodepth=64 --size=4G --runtime=60
sudo rbd device unmap -t nbd kube/perf-test
```

**Важные замечания по бенчмаркингу:**

*   Используйте `--direct=1` (O_DIRECT) для обхода page cache ядра и измерения реальной производительности хранилища.
*   Для тестов через `krbd` и `rbd-nbd` используйте `ioengine=libaio`, а не `ioengine=rbd`.
*   Предварительно создайте тестовый образ нужного размера и убедитесь, что кластер завершил начальную запись (все PG в `active+clean`).
*   Результаты бенчмарков могут отличаться в зависимости от текущей нагрузки кластера — выполняйте тесты в окно технического обслуживания или на изолированном тестовом кластере.

---

## Поиск неисправностей

| Симптом | Возможная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Лимиты QoS не применяются | Параметр задан неправильным уровнем (image вместо pool/global) или для клиента `krbd` | Проверьте `rbd config image get/list`. Для `krbd` используйте ограничения ОС (cgroup `io.max`/`ionice`) |
| PWL не активируется для образа | Не задан `rbd_plugins = pwl_cache`; `rbd_persistent_cache_mode` не `ssd`/`rwl`; размер кэша менее 1 GiB | Проверьте `rbd config image list \| grep persistent`, задайте `rbd_plugins` в `[client]` |
| PWL на PMEM работает медленно | Файловая система без DAX | Для `rwl` используйте DAX-раздел; иначе выбирайте режим `ssd` |
| После отключения PWL занимаемое место не освобождается | Файл кэша не удален | Выполните `rbd persistent-cache invalidate` перед `rbd_persistent_cache_mode disabled` |
| `rbd migration prepare` завершается ошибкой "in use" | Активные клиенты пишут/читают исходный образ | Остановите клиентов, повторите `prepare`; после `prepare` подключения только к целевому имени |
| После `commit` исходный образ пропал | Это штатное поведение (`commit` удаляет источник) | Если требуется сохранить источник — используйте `abort` до `commit` |
| Образ зеркалирования в статусе `down` | Нет сети до пиров, потеря кворума, нехватка exclusive-lock | Проверьте `ceph orch ps --daemon-type rbd-mirror`, логи демона, сетевую связность; для snapshot-режима удостоверьтесь в функциях `exclusive-lock`,`fast-diff` |
| `entries_behind` растет при journal-mirroring | Недостаточная пропускная способность канала | Увеличьте bandwidth между ЦОДами либо корректируйте расписание снапшотов для snapshot-режима |
| Split-brain после принудительного `promote --force` | Двусторонняя запись после аварийного переключения | Определите актуальный сайт, демотируйте отстающий, выполните `rbd mirror image resync` |
| Расписание снапшотов не создает зеркальные снимки | Модуль `rbd_support` отключен; расписание относится не к тому уровню (global/pool/image) | `ceph mgr module enable rbd_support`; проверьте `rbd mirror snapshot schedule ls --recursive` |
| Не удается мапнуть зашифрованный образ через `krbd` | Ядро клиента ниже 6.1 | Используйте `rbd-nbd`/QEMU или обновите ядро |
| Забыт/потерян файл passphrase зашифрованного образа | Секрет никогда не сохранялся в кластере | Данные невосстановимы без резервной копии заголовка LUKS и пароля — заблаговременно храните их в менеджере секретов |
| Низкая производительность зашифрованного образа | Невыровненные по сектору (4 КиБ для LUKS2) мелкие записи | Выравнивайте I/O по сектору, используйте больший `--order` образа, минимизируйте мелкоблочные записи |
| `rbd device map` завершается ошибкой «features not supported by kernel» | Ядро не поддерживает одну или более функций образа | Проверьте `rbd info kube/my-image \| grep features` и `uname -r`. Отключите неподдерживаемые функции через `rbd feature disable` или переключитесь на `rbd-nbd` |
| Образ заблокирован другим клиентом (Watcher) | Exclusive-lock удерживается другим процессом/хостом | Проверьте `rbd status kube/my-image` (раздел Watchers). Убедитесь, что предыдущий клиент корректно завершил работу. При необходимости — принудительный сброс `rbd lock remove` |
| TRIM/discard не освобождает место в пуле | Дискард отключен на уровне пула или ФС | Проверьте `ceph osd pool get kube rbd_discard`. Включите опцию `discard` при монтировании ФС или настройте периодический `fstrim` |
| Кэш librbd потребляет слишком много памяти | Суммарный `rbd_cache_size` × число образов превышает доступную память | Уменьшите `rbd_cache_size` на уровне пула или отключите кэш для отдельных образов (`rbd_cache=false`) |
| Ceph CSI PVC не расширяется | `allowVolumeExpansion: false` в StorageClass или драйвер не поддерживает расширение | Проверьте `kubectl get sc -o yaml`. Установите `allowVolumeExpansion: true` и пересоздайте StorageClass |
| Миграция образа зависла в состоянии `executing` | Прерывание сети или нехватка ресурсов during `execute` | Проверьте `rbd status <image>`. Выполните `abort` и повторите миграцию. Для больших образов увеличьте таймауты или снизьте нагрузку |

---

## Дополнительная информация

### Связанные темы
- [Обзор Ceph и RADOS](../ceph_overview.md) — архитектурная база.
- [RBD: Определения и концепции](./definitions_and_concepts.md) — основы технологии.
- [Управление образами RBD](./image_management.md) — создание, снапшоты, клоны.
- [Маппинг и монтирование](./mapping_and_mounting.md) — подключение устройств к ОС.
- [Установка и настройка клиента](./installation_and_setup.md) — подготовка окружения.
- [Операции Ceph](../Administration/operations.md) — управление кластером и OSD.
- [Бенчмаркинг через fio](../../../../Linux/Diagnostics/Filesystem/fio.md) — методика проверки оптимизаций.
- [TRIM/discard в Linux](../../../../Linux/SystemAdministration/fstrim_ssd_maintenance.md) — обслуживание SSD и освобождение пространства.

### Ресурсы
- [Official Ceph Docs: RBD Mirroring](https://docs.ceph.com/en/latest/rbd/rbd-mirroring/)
- [Official Ceph Docs: Image Live-Migration](https://docs.ceph.com/en/latest/rbd/rbd-live-migration/)
- [Official Ceph Docs: Persistent Write Log Cache](https://docs.ceph.com/en/latest/rbd/rbd-persistent-write-log-cache/)
- [Official Ceph Docs: Client-side Encryption](https://docs.ceph.com/en/latest/rbd/rbd-encryption/)
- [Official Ceph Docs: RBD Kernel Client (krbd)](https://docs.ceph.com/en/latest/rbd/rbd-ko/)
- [Ceph CSI: Encryption Guide](https://github.com/ceph/ceph-csi/blob/devel/docs/encryption.md)
- [Ceph CSI: RBD StorageClass Parameters](https://github.com/ceph/ceph-csi/blob/master/docs/rbd-usage.md)