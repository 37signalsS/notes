# `file`

## Определения

- **`file`:** Утилита для определения типа файла по содержимому, а не по расширению. Анализирует "магические числа" — уникальные последовательности байтов в начале файла.
- **Магические числа (Magic Numbers):** Сигнатуры форматов файлов, хранящиеся в базе данных `/etc/magic` или `/usr/share/misc/magic`. Позволяют надежно определять тип файла независимо от имени или расширения.
- **MIME-тип:** Стандартный формат указания типа контента (например, `application/zip`, `text/plain`, `application/x-executable`).

## Основные концепции

`file` анализирует содержимое файла, а не расширение, что позволяет:

- Определять тип файла с неверным или отсутствующим расширением
- Выявлять потенциально вредоносные файлы (например, `.jpg`, который на самом деле исполняемый)
- Проверять целостность файлов (соответствие ожидаемому формату)
- Автоматизировать обработку файлов в скриптах

**База данных магических чисел:**

- Расположение: `/etc/magic`, `/usr/share/misc/magic`
- Формат: последовательности байтов + маска + описание типа
- Обновляется с пакетами утилиты в дистрибутиве

## Практические сценарии

### Идентификация неизвестных файлов

```bash
# Определить тип архива
$ file archive.zip
archive.zip: Zip archive data, at least v1.0 to extract

# Определить исполняемый файл
$ file program.exe
program.exe: PE32 executable (GUI) Intel 80386, for MS Windows

# Определить скрипт
$ file script.sh
script.sh: POSIX shell script, ASCII text executable

# Распознать сжатый файл
$ file data.gz
data.gz: gzip compressed data, was "data.txt", last modified: ...
```

### Работа с особыми файлами

```bash
# Проверить символьную ссылку
$ file -L /bin/sh
/bin/sh: symbolic link to dash

# Определить тип блочного устройства
$ file -s /dev/sda1
/dev/sda1: Linux rev 1.0 ext4 filesystem data, ...

# Заглянуть внутрь сжатого файла
$ file -z archive.tar.gz
archive.tar.gz: gzip compressed data, from Unix, ... (tar archive)
```

## Дополнительная информация

### Ключевые опции

| Опция | Описание | Пример |
| :--- | :--- | :--- |
| `-b`, `--brief` | Без имени файла (для скриптов) | `file -b file.txt` |
| `-i`, `--mime` | MIME-тип + кодировка | `file -i file.pdf` |
| `-z`, `--compress` | Заглянуть внутрь сжатых | `file -z archive.gz` |
| `-s`, `--special-files` | Проверить спецфайлы (blk/char) | `file -s /dev/sda1` |
| `-L`, `--dereference` | Следовать по симлинкам | `file -L /bin/sh` |
| `-c`, `--checking-printout` | Показать parsed magic-правило | `file -c magic` |

### Распространенные MIME-типы

| Тип | Описание |
| :--- | :--- |
| `text/plain` | Обычный текст |
| `text/x-shellscript` | Shell-скрипт |
| `application/pdf` | PDF-документ |
| `application/zip` | ZIP-архив |
| `application/gzip` | GZIP-архив |
| `application/x-executable` | Исполняемый файл (ELF) |
| `application/x-dosexec` | DOS/Windows EXE |
| `image/jpeg`, `image/png` | Изображения |
| `application/octet-stream` | Двоичные данные (unknown) |

### Ограничения

- **Не все форматы распознаются:** Экзотические или проприетарные форматы могут определяться как `data`
- **Фрагментированные magic-файлы:** Кастомные правила требуют правильной компиляции (`file -C`)
- **Большие файлы:** Анализ может занимать время для файлов >1GB
- **Шифрованные файлы:** Определяются как случайные данные (`data`)

### Альтернативы и дополнения

| Инструмент | Назначение |
| :--- | :--- |
| `xdg-mime query filetype` | Определение по расширению (менее надежно) |
| `mimeopen` | Выбор приложения по MIME-типу |
| `trid` | Идентификация по расширенным сигнатурам |
| `exiftool` | Метаданные файлов (фото, документы) |

### См. также

- [Типы файлов в Linux](../../FileSystems/file_types.md)
- [Дескрипторы файлов](../../FileSystems/file_descriptors.md)
- [man 1 file](https://man7.org/linux/man-pages/man1/file.1.html)
- [File command source](https://github.com/file/file)
