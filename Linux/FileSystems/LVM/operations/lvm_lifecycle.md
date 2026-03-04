# Полный жизненный цикл LVM

> **SSoT:** Базовые определения PV, VG, LV см. в [Основных концепциях LVM](../overview_concepts.md).

## Этапы жизненного цикла

### 1. Подготовка диска и создание PV

- Добавьте новый диск (`/dev/sdc`).
- Создайте на нем раздел (`/dev/sdc1`) и пометьте его для LVM (`parted`, `set 1 lvm on`).
- Инициализируйте PV:

    ```bash
    sudo pvcreate /dev/sdc1
    ```

### 2. Создание VG и LV

```bash
sudo vgcreate my_vg /dev/sdc1
sudo lvcreate -L 1G -n my_test_lv my_vg
```

### 3. Форматирование и монтирование

```bash
sudo mkfs.ext4 /dev/my_vg/my_test_lv
sudo mkdir /mnt/test
sudo mount /dev/my_vg/my_test_lv /mnt/test
```

*(Не забудьте про [`/etc/fstab`](../../mounting/fstab.md#структура-и-синтаксис-файла-etcfstab) для постоянного монтирования)*.

### 4. Расширение "на лету"

- Добавьте еще один диск/раздел (`/dev/sdd1`) в VG: `pvcreate /dev/sdd1`, `vgextend my_vg /dev/sdd1`.
- Расширьте LV и файловую систему одной командой:

    ```bash
    sudo lvextend -L +500M -r /dev/my_vg/my_test_lv
    ```

### 5. Полное удаление (в обратном порядке)

```bash
sudo umount /mnt/test
sudo lvremove /dev/my_vg/my_test_lv
sudo vgreduce my_vg /dev/sdc1
sudo vgreduce my_vg /dev/sdd1
sudo pvremove /dev/sdc1 /dev/sdd1
```

## Дополнительная информация

См. также: [Создание PV, VG и LV](./pv_vg_creation.md), [Изменение размеров LVM](./lvm_resize.md), [Замена физического диска](./lvm_disk_replacement.md), [Просмотр информации](./lvm_view_info.md)
