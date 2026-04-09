# John the Ripper (JtR): Password Auditing

## Definitions

**John the Ripper (JtR)** — инструмент для офлайн-аудита и восстановления паролей. Подбирает пароли по их хешам из различных систем (Linux `/etc/shadow`, дампы БД, архивы). Поддерживает множество форматов хешей, работает на большинстве ОС.

## Basic Concepts

JtR принимает файл с хешами паролей и подбирает соответствующие пароли различными режимами атаки.

### Режимы работы

- **Wordlist mode (словарная атака):** Проверяет слова из файла-словаря (`wordlist`) как кандидаты на пароль
- **Single crack mode:** Генерирует вероятные пароли на основе имени пользователя (`testuser` → `testuser`, `testuser123`)
- **Incremental mode:** Полный [брутфорс](../Concepts/brute_force_attacks.md) — перебор всех комбинаций символов. Медленный, но исчерпывающий
- **External mode:** Кастомная генерация паролей через скрипты

### Файл `john.pot`

Взломанные пароли сохраняются в `~/.john/john.pot`. При каждой новой атаке JtR пропускает уже известные хеши.

## Practical Scenarios

### Аудит паролей Linux (`/etc/shadow`)

Объединение `/etc/passwd` и `/etc/shadow` через `unshadow`:

```bash
unshadow /etc/passwd /etc/shadow > hashes.txt
```

Автоматическое определение типа хеша и атака:

```bash
john hashes.txt
```

Атака с конкретным словарём:

```bash
john --wordlist=/usr/share/wordlists/rockyou.txt hashes.txt
```

### Взлом хеша из строки

```bash
echo "8743b52063cd84097a65d1633f5c74f5" > md5_hash.txt
john --format=raw-md5 md5_hash.txt
```

### Взлом пароля ZIP-архива

Извлечение хеша и атака:

```bash
zip2john my_archive.zip > zip_hash.txt
john zip_hash.txt
```

### Просмотр результатов

```bash
john --show hashes.txt
```

## Additional Information

### Правила (Rules)

Правила трансформируют слова из словаря: добавляют цифры, заменяют символы (`a` → `@`, `s` → `$`), меняют регистр. Повышают эффективность словарной атаки.

```bash
john --wordlist=pass.list --rules hashes.txt
```

Правила настраиваются в `john.conf`.

### Jumbo John

Расширенная версия **Jumbo John** поддерживает больше форматов хешей, GPU-ускорение через OpenCL и дополнительные утилиты (`ssh2john`, `pdf2john`, `rar2john`). Рекомендуется для профессионального использования.

### Сравнение с другими инструментами

- **[Hashcat](https://hashcat.net/hashcat/):** Фокус на GPU-ускорении и скорости перебора. JtR сильнее в словарных атаках с правилами и автоматическом определении форматов.
- **[Fail2ban](../../Linux/Security/Tools/fail2ban.md):** Защита от онлайн-брутфорса (rate-limit, бан IP). JtR — офлайн-аудит уже украденных хешей.
