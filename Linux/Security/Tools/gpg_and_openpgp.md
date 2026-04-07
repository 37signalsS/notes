# gpg and openpgp

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

## Definitions

**OpenPGP** — протокол и спецификация шифрования на основе асимметричных алгоритмов для шифрования, подписи и дешифрования сообщений.

**GnuPG (GPG)** — CLI-утилита, реализующая спецификацию OpenPGP.

## Basic Concepts

### Типы шифрования

| Характеристика | Симметричное | Асимметричное |
|----------------|-------------|---------------|
| Ключей | Один | Два (публичный + приватный) |
| Скорость | Высокая | Низкая |
| Управление ключами | Сложное (безопасная передача) | Простое (публичный ключ свободно распространяется) |
| Применение | Большие объемы данных | Обмен ключами, цифровые подписи |

### Гибридное шифрование

Основа PGP/GPG — комбинация обоих методов:

1. Генерация случайного одноразового **симметричного** ключа.
2. Шифрование данных симметричным ключом (быстро).
3. Шифрование симметричного ключа **асимметричным** алгоритмом (публичный ключ получателя).
4. Отправка зашифрованных данных + зашифрованного симметричного ключа.
5. Получатель расшифровывает симметричный ключ своим приватным, затем данные — симметричным.

### Ключи PGP

- **Приватный ключ** — создание подписей, расшифровка. **Хранить в секрете.**
- **Публичный ключ** — проверка подписей, шифрование для владельца. Свободно распространяется.

### Сеть доверия (Web of Trust)

Децентрализованная модель аутентификации. Вместо CA участники самостоятельно подписывают публичные ключи других пользователей своим приватным ключом, подтверждая доверие.

### Мастер-ключ и подключи (Sub-keys)

Система разделения ключей для безопасности:

- **Мастер-ключ (Certify):**
  - Только для управления: подпись/отзыв подключей, подпись чужих ключей (WoT)
  - **Хранится офлайн** (сейф, зашифрованный USB)
  - Имеет срок истечения
  - Заранее создается **сертификат отзыва**

- **Подключи:**
  - Генерируются из мастер-ключа для повседневных задач: шифрование (Encrypt), подпись (Sign), аутентификация (Authenticate)
  - Могут быть отозваны мастер-ключом без отзыва всей связки

## Practical Scenarios

### Настройка клиента

Конфигурация `~/.gnupg/gpg.conf`:

```ini
keyid-format short
throw-keyids
no-emit-version
no-comments
keyserver hkps://keys.openpgp.org
```

### Генерация мастер-ключа

```sh
gpg --full-generate-key --expert
```

- **Тип:** `(9) ECC (sign and encrypt)`
- **Кривая:** `(1) Curve 25519`
- **Срок:** `2y` (можно изменить позже)
- **UID:** реальные имя и Email

### Добавление подключей

```sh
gpg --edit-key --expert <UserID>
```

В редакторе `gpg>`:

1. **Подпись:** `addkey` → `(10) ECC (sign only)` → `Curve 25519` → срок `2y`
2. **Аутентификация:** `addkey` → `(11) ECC (set your own capabilities)` → отключить `Sign` (S), включить `Authenticate` (A) → `Curve 25519` → срок `2y`
3. Сохранить: `save`

### Экспорт и резервное копирование

```sh
# Публичный ключ
gpg --export -a <UserID> > public_key.asc

# Приватные подключи (для рабочих устройств)
gpg --export-secret-subkeys -a <UserID> > private_subkeys.asc

# Приватный мастер-ключ (только бэкап)
gpg --export-secret-keys -a <UserID> > private_master_key.asc

# Сертификат отзыва
gpg -a --gen-revoke <UserID> > revocation_certificate.asc
```

Мастер-ключ и сертификат отзыва хранить в разных надежных местах (зашифрованный USB в сейфе).

### Удаление мастер-ключа с рабочей машины

```sh
# Указать ID мастер-ключа с восклицательным знаком
gpg --delete-secret-key <MasterKeyID>!
```

Повседневные задачи работают только через подключи.

### Импорт ключей

```sh
gpg --import <file.asc>
```

### Подписи

```sh
# Clear-sign (текст виден)
gpg --clear-sign file.txt

# Detached signature (отдельная подпись)
gpg --detach-sign -a file.zip

# Проверка подписи
gpg --verify file.zip.asc file.zip       # detached
gpg --decrypt signed_file.asc            # clear-sign / embedded
```

### Шифрование и расшифровка

```sh
# Асимметричное (для получателя)
gpg -e -a -r <Recipient_UserID> file.txt

# Шифрование + подпись
gpg -e -a -s -r <Recipient_UserID> file.txt

# Симметричное (пароль, без ключей)
gpg -c -a file.txt

# Расшифровка
gpg -d file.txt.asc
```

### Серверы ключей

```sh
# Отправить ключ
gpg --send-keys <UserID>

# Получить ключ
gpg --recv-keys <UserID>

# Обновить все локальные ключи
gpg --refresh-keys
```

### Подпись коммитов в Git

```ini
# ~/.gitconfig
[user]
  email = email_из_uid
  name = имя
  signingkey = <ID_ключа_подписи>!
```

```sh
git config --global commit.gpgsign true
git commit -S -m "Подписанный коммит"
```

Подробнее: [git configuration](../../../../Git/git_configuration.md)

### Аутентификация по SSH через GPG-Agent

GPG-Agent заменяет ssh-agent:

1. `~/.gnupg/gpg-agent.conf`:
   ```
   enable-ssh-support
   ```

2. Получить keygrip и добавить в `~/.gnupg/sshcontrol`:
   ```sh
   gpg -K --with-keygrip <AuthKeyID>!
   echo "<KEYGRIP>" >> ~/.gnupg/sshcontrol
   ```

3. Настроить переменные окружения в `.bashrc`/`.zshrc` на сокет `gpg-agent`.

4. Экспорт SSH-ключа для сервера:
   ```sh
   gpg --export-ssh-key <AuthKeyID>!
   ```

Подробнее: [SSH key management](../../../../Linux/Security/ssh/keys/ssh_key_management.md)

## Additional Information

### Связанные темы

- [backup security](../../../../Databases/Concepts/backup_security.md) — шифрование бэкапов через GPG
- [artifact signing](../../../../Security/Supply_Chain_Security/artifact_signing.md) — подпись артефактов (GPG/Minisign)
- [sops overview](../../../../Security/Tools/sops_overview.md) — шифрование секретов (PGP/GPG как один из бэкендов)
- [Linux security mechanisms](../../Linux_Security_Mechanisms_Overview.md) — GPG в экосистеме безопасности Linux

### Best Practices

1. Мастер-ключ хранить **офлайн**, использовать только подключи
2. Устанавливать срок действия ключей (можно продлить)
3. Заранее генерировать сертификат отзыва
4. Использовать ECC (Curve 25519) вместо RSA — быстрее, меньше размер ключа
5. Не передавать приватные ключи по незащищенным каналам
6. Регулярно обновлять ключи с сервера (`--refresh-keys`)
7. Для бэкапов бэкапов использовать зашифрованные носители
