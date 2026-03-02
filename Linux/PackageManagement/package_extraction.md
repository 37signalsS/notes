# Извлечение содержимого пакетов

## Практические сценарии

### DEB-based системы

Пакет `.deb` — это архив `ar`, содержащий `control.tar.gz` (метаданные) и `data.tar.gz` (файлы).

* **Распаковать с `dpkg-deb`:** `dpkg-deb --extract <package_name.deb> <output_dir>`
* **Распаковать вручную с `ar`:** `ar x <package_name.deb>` (создаст `control.tar.gz`, `data.tar.gz`, `debian-binary`).

### RPM-based системы

RPM-пакет содержит бинарный заголовок и `cpio` архив с содержимым.

* **Распаковать с `rpm2cpio` и `cpio`:** `rpm2cpio <package_name.rpm> | cpio -idmv`

---

См. также: [Обзор управления пакетами в Linux](./linux_package_management_overview.md)
