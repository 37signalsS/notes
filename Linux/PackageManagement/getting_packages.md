# Получение файлов пакетов

## Практические сценарии

Получение файла пакета без немедленной установки (например, для анализа или переноса).

### DEB-based системы

* **Скачать пакет:** `apt-get download <package_name>`
* **Скачать пакет со всеми зависимостями (в кэш `/var/cache/apt/archives/`):** `apt-get install --download-only <package_name>`
* **Поиск пакета по содержимому файла (утилита `apt-file`):**

    ```bash
    sudo apt-get update && sudo apt-get install apt-file && apt-file update
    apt-file search <file_path_or_name>
    ```

* **Поиск пакета, которому принадлежит файл (`dpkg`):** `dpkg -S <file_path>`

### RPM-based системы

* **Скачать пакет:** `dnf download <package_name>`
* **Скачать пакет со всеми зависимостями:** `dnf install --downloadonly <package_name>`
* **Поиск пакета по содержимому файла:** `dnf provides '*/<file_name>'`

### Поиск пакетов в веб-интерфейсе

* **Debian:** [packages.debian.org](https://packages.debian.org/)
* **Fedora/CentOS/RHEL:** [packages.fedoraproject.org](https://packages.fedoraproject.org/)

---

См. также: [Обзор управления пакетами в Linux](./linux_package_management_overview.md)
