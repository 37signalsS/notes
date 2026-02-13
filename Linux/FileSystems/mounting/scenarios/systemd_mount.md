# Сценарий: Монтирование по требованию с помощью Systemd

## 1. Юнит `.mount` для постоянного монтирования

Юнит `.mount` определяет параметры монтирования. Его имя строится по пути к точке монтирования, где `/` заменяется на `-`. Например, для `/mnt/share` файл будет называться `mnt-share.mount`.

Пример `/etc/systemd/system/mnt-share.mount`:

```ini
[Unit]
Description=Mount network share
After=network-online.target  # Убедиться, что сеть доступна

[Mount]
What=//192.168.0.10/share
Where=/mnt/share
Type=cifs
Options=credentials=/etc/smb.cred,_netdev,vers=3.0

[Install]
WantedBy=multi-user.target
```

**Пояснения к секциям:**

* **`[Unit]`**: Общие метаданные для юнита. `Description` — описание, `After=network-online.target` — указывает, что юнит должен запускаться только после того, как будет доступна сеть (важно для сетевых ресурсов).
* **`[Mount]`**: Определяет параметры монтирования.
  * `What` — ресурс для монтирования (например, сетевая папка, как в примере `//192.168.0.10/share`).
  * `Where` — точка монтирования в локальной файловой системе (`/mnt/share`).
  * `Type` — тип файловой системы (`cifs` для SMB/CIFS, `nfs` для NFS, `ext4` для локальных дисков и т.д.).
  * `Options` — опции монтирования, аналогичные опциям в `/etc/fstab`. `_netdev` указывает, что это сетевой ресурс.
* **`[Install]`**: Определяет, как юнит будет интегрирован в систему при включении (`enable`). `WantedBy=multi-user.target` означает, что юнит будет запускаться при переходе в многопользовательский режим (стандартный режим работы сервера).

После создания файла юнита необходимо:

1. Создать точку монтирования: `sudo mkdir -p /mnt/share`
2. Перезагрузить systemd: `sudo systemctl daemon-reload`
3. Включить юнит для автоматического запуска при загрузке: `sudo systemctl enable mnt-share.mount`
4. Запустить юнит сейчас: `sudo systemctl start mnt-share.mount`
5. Проверить статус: `sudo systemctl status mnt-share.mount`

## 2. Юнит `.automount` для монтирования по требованию

Юнит `.automount` позволяет монтировать ресурс только при первом обращении к нему. Это ускоряет загрузку системы, если сетевые ресурсы не нужны сразу, или если сеть еще не поднята. Он работает в паре с соответствующим `.mount` юнитом.

Пример содержимого файла `mnt-share.automount` (например, `/etc/systemd/system/mnt-share.automount`):

```ini
[Unit]
Description=Automount network share

[Automount]
Where=/mnt/share
TimeoutIdleSec=600  # Отмонтировать через 10 минут бездействия

[Install]
WantedBy=multi-user.target
```

**Активация монтирования по требованию:**

```sh
sudo mkdir -p /mnt/share
sudo systemctl daemon-reload
# Включаем и запускаем только .automount юнит
sudo systemctl enable --now mnt-share.automount
sudo systemctl status mnt-share.automount
```

При первой попытке доступа к `/mnt/share` systemd автоматически активирует `mnt-share.mount`.
