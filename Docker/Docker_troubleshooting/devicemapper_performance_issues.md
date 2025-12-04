# Низкая производительность Docker в CentOS/RHEL 7 (драйвер devicemapper)

В старых версиях Docker на CentOS 7 и RHEL 7 по умолчанию использовался драйвер хранения `devicemapper`. Без дополнительной настройки он работал в режиме `loopback` (`loop-lvm`), который **категорически не подходил для production-сред**.

**Симптомы:**

*   Крайне низкая производительность операций ввода-вывода (I/O) внутри контейнеров.
*   Постепенная деградация производительности файловой системы, вплоть до полной остановки.
*   Нестабильная работа и риск потери данных.
*   Вывод команды `docker info` показывал наличие `Data loop file` и `Metadata loop file`.

```
$ docker info
...
Storage Driver: devicemapper
 Pool Name: docker-thinpool
 Pool Blocksize: 65.54 kB
 Base Device Size: 10.74 GB
 Backing Filesystem: xfs
 Data file: /var/lib/docker/devicemapper/devicemapper/data
 Metadata file: /var/lib/docker/devicemapper/devicemapper/metadata
 Data loop file: /var/lib/docker/devicemapper/devicemapper/data
 Metadata loop file: /var/lib/docker/devicemapper/devicemapper/metadata
...
```

Причина в том, что режим `loopback` эмулирует блочное устройство через файлы на основной файловой системе, создавая несколько медленных слоев абстракции.

### Решение: Настройка `direct-lvm` Thin Pool

Правильным решением для production-среды было переключение `devicemapper` в режим `direct-lvm`. Этот режим работает напрямую с блочными устройствами LVM, что значительно быстрее и стабильнее.

**Общий план действий:**

1.  **Подготовить блочное устройство:** Выделить отдельный диск, раздел или LVM-том для Docker.
2.  **Создать LVM Thin Pool:**
    *   Создать физический том (`pvcreate`).
    *   Создать группу томов (`vgcreate`).
    *   Создать два логических тома (один для данных, другой для метаданных) и объединить их в `thin pool` с помощью `lvconvert`.
3.  **Настроить Docker:** Указать Docker использовать `devicemapper` с созданным `thin pool` через конфигурационный файл `/etc/docker/daemon.json`.

**Пример конфигурации `/etc/docker/daemon.json`:**

```json
{
    "storage-driver": "devicemapper",
    "storage-opts": [
        "dm.thinpooldev=/dev/mapper/vg-thinpool",
        "dm.use_deferred_removal=true",
        "dm.use_deferred_deletion=true"
    ]
}
```
После этого в `docker info` поля `Data loop file` и `Metadata loop file` должны исчезнуть.

Драйвер `devicemapper` считается устаревшим и был **удален в Docker 25.0**.

Современным, более производительным и простым в настройке драйвером для всех дистрибутивов Linux является **[`overlay2`](../Docker_fs/docker_overlayfs.md)**. При возможности всегда следует использовать его.
