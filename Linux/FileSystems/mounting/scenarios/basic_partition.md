# Сценарий: Быстрое добавление нового раздела

Полный рабочий процесс добавления нового диска:

```bash
# 1. Создаём точку монтирования
sudo mkdir /data

# 2. Определяем UUID раздела
sudo blkid /dev/sdc1

# 3. Добавляем в /etc/fstab
# UUID=xxx /data ext4 defaults 0 2
echo 'UUID=xxx /data ext4 defaults 0 2' | sudo tee -a /etc/fstab

# 4. Применяем изменения
sudo mount -a

# 5. Проверяем
sudo df -h /data
```
