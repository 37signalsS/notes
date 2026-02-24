### Полное удаление RAID-массива

1. **Отмонтировать файловую систему**: `sudo umount /dev/md0` и удалить запись из `/etc/fstab`.
2. **Остановить массив**: `sudo mdadm --stop /dev/md0`.
3. **Затереть суперблоки**: **Важнейший шаг**, удаляющий метаданные RAID с дисков.

    ```bash
    sudo mdadm --zero-superblock /dev/sdb1
    sudo mdadm --zero-superblock /dev/sdc1
    # ... и так далее для всех дисков
    ```

4. **Удалить конфигурацию**: Удалите строку из `/etc/mdadm/mdadm.conf` и обновите `initramfs`.
