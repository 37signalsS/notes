# Ansible: Модули управления PKI и сертификатами

## Определения

**Модули PKI (Public Key Infrastructure)** — модули коллекции `community.crypto`, которые выполняют криптографические операции на управляемом хосте средствами Python-библиотеки `cryptography`: генерацию приватных ключей, формирование CSR, выпуск и проверку сертификатов X.509, сборку PKCS#12-архивов. Операции выполняются **на управляемом хосте**, а не вызовом утилиты `openssl` через `command`.

**Коллекция `community.crypto`** — официальная коллекция Ansible, **не входящая в `ansible-core`**. Устанавливается отдельно: `ansible-galaxy collection install community.crypto`. Проверенная актуальная версия — **3.4.0**.

**`cryptography`** — Python-библиотека, выполняющая всю криптографию. **Требуется на управляемом хосте** (не на контрольном узле), версия **>= 3.3**. Это ключевое отличие от модулей `community.general`, где зависимости ставятся на контрольный узел.

**Приватный ключ (private key)** — секретный ключ асимметричной пары. Файл создаётся с правами `0600` по умолчанию. Утечка приватного ключа означает возможность подделки сертификата без компрометации CA.

**CSR (Certificate Signing Request)** — запрос на подпись, содержащий Subject, Subject Alternative Names и **публичный** ключ. Создаётся модулем `community.crypto.openssl_csr`. Сам по себе не является сертификатом.

**Сертификат X.509** — подписанный документ, связывающий Subject/SAN с публичным ключом. Выпускается модулем `community.crypto.x509_certificate` одним из провайдеров.

**Провайдер (`provider`)** — способ выпуска сертификата в `x509_certificate`. Актуальные значения в `community.crypto` 3.x: `selfsigned`, `ownca`, `acme`. Провайдер `entrust` **удалён в 3.0.0** ( sunsetting API ECS), `assertonly` — **удалён в 2.0.0**.

> **Устаревшее имя модуля:** До `community.crypto` 3.x модуль выпуска сертификатов назывался `community.crypto.openssl_certificate` (в `ansible-core` до 2.9). Сейчас корректное FQCN — `community.crypto.x509_certificate`. Старое короткое имя `ansible.builtin.openssl_certificate` всё ещё работает через перенаправление, но генерирует предупреждение об устаревании. В новых плейбуках используйте `x509_certificate`.

**CA (Certificate Authority)** — удостоверяющий центр: сертификат с `basicConstraints: CA:TRUE`, которым подписываются сертификаты конечных сущностей.

**`ASN.1 TIME`** — формат timestamps, который возвращают модули `community.crypto` (`YYYYMMDDHHMMSSZ`, всегда UTC), например `20260418120000Z`. Это **не** ISO 8601, поэтому `| to_datetime('%Y-%m-%dT%H:%M:%SZ')` к такому значению неприменим.

### Требования к версиям

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **ansible-core** | 2.17+ | community.crypto 3.4.0 поддерживает ansible-core 2.17.0 и новее |
| **community.crypto** | 3.0+ | Проверено на 3.4.0. Не входит в `ansible-core` |
| **cryptography** (управляемые хосты) | 3.3+ | Ставится на каждый управляемый хост, а не на контрольный узел |
| **Python** (управляемые хосты) | 3.9+ | Для `community.crypto` 3.x |

**Проверка окружения:**
```bash
ansible-galaxy collection install community.crypto
ansible-galaxy collection list | grep crypto
# → community.crypto 3.4.0

# Проверка cryptography на управляемом хосте
ansible all -m ansible.builtin.command -a "python3 -c 'import cryptography; print(cryptography.__version__)'"
ansible all -m ansible.builtin.command -a "python3 -c 'import cryptography; print(cryptography.__version__)'" -b
# → 3.4.0   (без -b обычно Permission denied или пустой вывод)
```

### Группы модулей по назначению

1.  **Приватные ключи:**
    *   `community.crypto.openssl_privatekey`: Генерация ключей RSA, DSA, ECC, Ed25519, Ed448, X25519, X448, а также постквантовых ML-DSA-44/65/87 (требуют `cryptography` 47.0.0+). Поддерживает шифрование паролем и форматы PKCS#1/PKCS#8/DER.
    *   `community.crypto.openssl_privatekey_info`: Только чтение информации о существующем ключе (без генерации). Идемпотентен по определению.
    *   `community.crypto.openssl_privatekey_pipe`: Генерация ключа без записи на диск — возвращает содержимое в память. Применяется для tmpfs/агентиless-сценариев, где ключ не должен касаться диска.
2.  **Публичные ключи и параметры:**
    *   `community.crypto.openssl_publickey`: Извлечение/генерация публичного ключа из приватного. Нужен для распространения ключа без раскрытия приватного.
    *   `community.crypto.openssl_publickey_info`: Чтение свойств публичного ключа.
    *   `community.crypto.openssl_dhparam`: Генерация параметров Диффи-Хеллмана. Долгая операция (минуты-десятки минут) — только для legacy-серверов со старыми DH-параметрами.
3.  **Конвертация форматов:**
    *   `community.crypto.openssl_privatekey_convert`: Смена формата приватного ключа (PKCS#1 ↔ PKCS#8 ↔ DER) **без перегенерации** — в отличие от `openssl_privatekey`, который при смене формата создаёт новый ключ.
    *   `community.crypto.x509_certificate_convert`: Конвертация сертификата между PEM и DER без перевыпуска.
4.  **Запросы на подпись (CSR):**
    *   `community.crypto.openssl_csr`: Создание CSR с Subject, SAN, подписью ключа. `privatekey_content` позволяет передать ключ из памяти, не укладывая его на диск.
    *   `community.crypto.openssl_csr_info`: Чтение и **проверка подписи CSR**; модуль падает, если подпись невалидна. Существует и как фильтр `community.crypto.openssl_csr_info` для разбора CSR в памяти.
    *   `community.crypto.openssl_csr_pipe`: Аналог `openssl_csr` без записи на диск.
5.  **Сертификаты:**
    *   `community.crypto.x509_certificate`: Выпуск сертификата провайдером `selfsigned`, `ownca` или `acme`. Умеет проверять соответствие существующего файла заданным параметрам и перевыпускать при расхождении.
    *   `community.crypto.x509_certificate_info`: Чтение свойств сертификата — `expired`, `not_after`, `not_before`, `subject`, `subject_alt_name`, `issuer`, `is_ca`, `self_signed`, `basic_constraints`, `key_usage`, `extended_key_usage`, `valid_at`. Существует и как фильтр `community.crypto.x509_certificate_info` для разбора сертификата из строки.
    *   `community.crypto.x509_certificate_pipe`: Выпуск без записи на диск.
6.  **Цепочки и отзыв:**
    *   `community.crypto.certificate_complete_chain`: Достраивает цепочку сертификатов по заданным недоверенным и корневым сертификатам. Правильный способ сформировать `ca_bundle.crt` вместо ручной конкатенации.
    *   `community.crypto.x509_crl`: Генерация списка отзыва (CRL) — механизм отзыва для внутренних CA.
    *   `community.crypto.x509_crl_info`: Чтение CRL, включая состав отозванных сертификатов.
7.  **Экспорт и упаковка:**
    *   `community.crypto.openssl_pkcs12`: Сборка приватного ключа, сертификата и цепочки в один зашифрованный `.p12`-архив. Требует `passphrase` для защиты содержимого.
    *   `community.crypto.openssl_pkcs12_info`: Разбор существующего `.p12` без изменения.
    *   `community.crypto.openssl_pkcs12_extract`: Извлечение сертификата и ключа из `.p12` в отдельные файлы.
8.  **SSH-сертификаты и подписи:**
    *   `community.crypto.openssh_keypair`: Генерация пары SSH-ключей в формате OpenSSH.
    *   `community.crypto.openssh_cert`: Выпуск сертификата OpenSSH для пользователя или хоста — альтернатива управлению `authorized_keys` на каждом хосте.
    *   `community.crypto.openssl_signature` / `openssl_signature_info`: Подпись данных и проверка подписи.
9.  **Обслуживание шифрованных дисков и окружения:**
    *   `community.crypto.luks_device`: Управление зашифрованными устройствами LUKS. Подробно — в [модулях управления хранилищем](ansible_storage_and_disk_management_modules.md).
10. **ACME (Let's Encrypt и совместимые):**
    *   `community.crypto.acme_account` / `acme_account_info`: Регистрация и чтение ACME-аккаунта.
    *   `community.crypto.acme_certificate`: Создание сертификата по протоколу ACME — основной модуль для автоматизации выпуска.
    *   `community.crypto.acme_certificate_order_create` / `_order_info` / `_order_validate` / `_order_finalize`: Низкоуровневое управление жизненным циклом заказа, если нужен контроль над отдельными шагами.
    *   `community.crypto.acme_certificate_renewal_info`: Проверка через протокол ARI, нужно ли продлевать сертификат.
    *   `community.crypto.acme_certificate_revoke`: Отзыв сертификата.
    *   `community.crypto.acme_challenge_cert_helper`: Подготовка сертификата для ACME-челленджа `tls-alpn-01`.
    *   `community.crypto.acme_ari_info`, `acme_inspect`: Получение ARI-информации и диагностические запросы к ACME-серверу.
    *   `community.crypto.get_certificate`: **Получение сертификата, который предъявляет удалённый хост** по `host:port`. Не ACME-модуль: применяется для инвентаризации и аудита TLS-эндпоинтов, например для проверки, какой сертификат отдаёт чужой сервис.

## Основные концепции

### Как устроен выпуск сертификата

Цепочка всегда одинакова — модули выполняются строго в этом порядке:

```
openssl_privatekey  →  openssl_csr  →  x509_certificate  →  openssl_pkcs12
   (ключ)              (запрос)         (сертификат)           (экспорт)
                            ↑
                     ownca_path / ownca_content
                     (сертификат и ключ CA — только для ownca)
```

Нарушение порядка приводит к ошибке `privatekey does not exist` или `csr does not exist`. Для `provider: ownca` дополнительно требуются сертификат CA (`ownca_path`) и, если CSR не содержит публичного ключа, приватный ключ CA (`ownca_privatekey_path`).

### Ключевой параметр `regenerate` и идемпотентность

Самая опасная особенность модулей `community.crypto` в том, что они **перегенерируют** существующий файл, если он не соответствует заданным параметрам. Например, смена `size` с 4096 на 2048 приведёт к созданию **нового** приватного ключа — и всё, что зашифровано старым ключом, перестанет читаться.

`openssl_privatekey` управляет этим поведением через `regenerate`:

| Значение | Поведение |
| :--- | :--- |
| `full_idempotence` | Перегенерирует при любом несовпадении, включая нечитаемый файл или неверную passphrase (по умолчанию) |
| `partial_idempotence` | Перегенерирует только при несовпадении параметров, но **не** перезапишет нечитаемый ключ или ключ с неизвестной passphrase |
| `never` | Никогда не перегенерирует существующий ключ; падает при невозможности прочитать |
| `fail` | Падает, если ключ не соответствует заданным параметрам |
| `always` | Всегда перегенерирует (эквивалент `force: true`) |

**Рекомендация для production:** `regenerate: partial_idempotence` вместе с `backup: true`. Значение `always` полностью отключает идемпотентность модуля — атрибут `idempotent` в документации прямо помечен как **partial**.

Параметр `format_mismatch` управляет отдельно: `regenerate` (по умолчанию) заменяет ключ при смене формата, `convert` конвертирует существующий, сохраняя сам ключ.

### `ignore_timestamps` и относительное время

`x509_certificate` по умолчанию игнорирует метки `not_before`/`not_after` при проверке идемпотентности (`ignore_timestamps: true`). Это сделано специально для относительных сроков вроде `+365d`: иначе каждый запуск в другое время считал бы сертификат изменившимся и выпускал бы новый.

Следствие: **изменение срока действия не приведёт к перевыпуску**, пока `ignore_timestamps: true`. Чтобы срок применялся, нужен `ignore_timestamps: false`, но тогда относительное время (`+365d`) ломает идемпотентность — модуль будет перевыпускать сертификат при каждом запуске. Компромисс: абсолютный timestamp (`20270401000000Z`) вместе с `ignore_timestamps: false`.

### Формат времени в возвращаемых значениях

Модули `*_info` возвращают даты в ASN.1 TIME (`YYYYMMDDHHMMSSZ`, UTC). Это **не** ISO 8601, поэтому фильтр `to_datetime` с форматом по умолчанию (`%Y-%m-%dT%H:%M:%SZ`) на таком значении не сработает. Решение — передать нужный формат явно:

```yaml
# Правильно: явный формат ASN.1 TIME
{{ cert.not_after | to_datetime('%Y%m%d%H%M%SZ') }}

# Неправильно: значение не в ISO 8601, будет исключение
{{ cert.not_after | to_datetime }}
```

Отдельного фильтра для конвертации ASN.1 TIME в UNIX-время в `community.crypto` **нет** (в коллекции есть только `gpg_fingerprint`, `parse_serial`, `to_serial`, `split_pem` и `*_info`-фильтры). Если нужен epoch-формат, преобразуйте через `to_datetime`, а затем в шаблоне:

```yaml
- name: "Преобразовать not_after в datetime"
  ansible.builtin.set_fact:
    cert_not_after: "{{ cert.not_after | to_datetime('%Y%m%d%H%M%SZ') }}"

- name: "Остаток срока в днях (через UNIX-время)"
  ansible.builtin.set_fact:
    cert_days_left: "{{ ((cert_not_after | int) - (ansible_facts.epoch | int)) // 86400 }}"
```

Проще всего остаться на пороговых проверках `valid_at` — они не требуют преобразования дат вовсе и читаются как намерение: «проверить, что сертификат действителен ещё 30 дней».

### Параметр `no_log` и секреты

`passphrase` (пароль приватного ключа) и содержимое ключа — секреты. Модули возвращают их в вывод при `return_content: true`, а `openssl_pkcs12` всегда возвращает содержимое архива. Поэтому:

- `no_log: true` на любой задаче с `passphrase` обязателен.
- Пароли берутся из Ansible Vault, а не из `vars` в открытом виде.
- `return_content: true` используйте только в связке с `no_log: true`.

### Идемпотентность и режимы диагностики

| Модуль | check_mode | diff_mode | Идемпотентность |
| :--- | :--- | :--- | :--- |
| `openssl_privatekey` | full | full | partial (`regenerate: always` отключает) |
| `x509_certificate` | full | full | Да, при `ignore_timestamps: true` для относительных сроков |
| `x509_certificate_info` | full | — | Да (только чтение) |
| `openssl_csr` | full | full | Да |
| `openssl_pkcs12` | full | — | Да (содержимое архива нестабильно, учитывайте это в проверках) |
| Модули `*_info` | full | — | Да (только чтение) |

### Модель выполнения: контроллер vs управляемый хост

Все модули `community.crypto` выполняют криптографические операции **на управляемом хосте**, а не на контрольном узле Ansible. Это означает:

- Библиотека `cryptography` должна быть установлена на целевом хосте (не на машине, где запускается `ansible-playbook`).
- Приватные ключи, CSR и сертификаты физически создаются на управляемом хосте.
- `delegate_to` используется, когда CA-операции должны выполняться на выделенном хосте (сценарий 5), но сам модуль `x509_certificate` всё равно работает на том хосте, на который указывает `delegate_to`.
- Модули `*_pipe` возвращают содержимое в переменную без записи на диск управляемого хоста, но генерация ключа всё равно происходит там же, только результат удерживается в памяти Ansible.

Это отличает `community.crypto` от утилитарных модулей (`command`, `shell`), которые могут запускать `openssl` на хосте и возвращать stdout.

## Практические сценарии

### Сценарий 1: Внутренний CA и выпуск сертификата сервиса

Полный цикл на одном хосте: создание ключа и CSR, самоподписанный сертификат CA, выпуск сертификата сервиса, выгрузка публичного ключа.

```yaml
---
- name: "Выпуск внутреннего CA и сертификата сервиса"
  hosts: ca_server
  become: true
  vars:
    crypto_dir: /etc/pki/internal
    service_name: app.example.com
    service_ip: "192.0.2.10"
    cert_validity: "+825d"

  tasks:
    - name: "Создать каталоги для PKI"
      ansible.builtin.file:
        path: "{{ crypto_dir }}"
        state: directory
        mode: "0700"
        owner: root
        group: root
    # → changed: [ca_server] => {"changed": true, "msg": "Created directory"}

    - name: "Приватный ключ и самоподписанный сертификат CA"
      community.crypto.openssl_privatekey:
        path: "{{ crypto_dir }}/ca.key"
        type: RSA
        size: 4096
        mode: "0600"
        regenerate: partial_idempotence
        backup: true
    # → changed: [ca_server] => {"changed": true, "type": "RSA", "size": 4096, "filename": "/etc/pki/internal/ca.key"}
    # повторный запуск: ok: [ca_server] => {"changed": false}

    - name: "Сертификат CA (10 лет)"
      community.crypto.x509_certificate:
        path: "{{ crypto_dir }}/ca.crt"
        privatekey_path: "{{ crypto_dir }}/ca.key"
        csr_content: |
          [req]
          req_extensions = v3_ca
          distinguished_name = req_distinguished_name
          prompt = no
          [req_distinguished_name]
          CN = Example Internal CA
          O = Example
          [v3_ca]
          basicConstraints = critical,CA:TRUE
          keyUsage = critical,digitalSignature,cRLSign,keyCertSign
          subjectKeyIdentifier = hash
        provider: selfsigned
        mode: "0644"
    # → changed: [ca_server] => {"changed": true, "filename": "/etc/pki/internal/ca.crt"}

    - name: "Приватный ключ сервиса"
      community.crypto.openssl_privatekey:
        path: "{{ crypto_dir }}/{{ service_name }}.key"
        type: ECC
        curve: secp384r1
        mode: "0600"
        regenerate: partial_idempotence
    # ECC вместо RSA: ключ и сертификат меньше при сопоставимой стойкости
    # → changed: [ca_server] => {"changed": true, "type": "ECC", "curve": "secp384r1", "filename": "/etc/pki/internal/app.example.com.key"}

    - name: "Собрать каталог (CA + сертификат сервиса) для проверки цепочки"
      community.crypto.certificate_complete_chain:
        path: "{{ crypto_dir }}/{{ service_name }}.crt"
        intermediate_certs:
          - "{{ crypto_dir }}/intermediate.crt"
        root_certificates:
          - "{{ crypto_dir }}/ca.crt"
        output: "{{ crypto_dir }}/{{ service_name }}_chain.crt"
        mode: "0644"
    # Модуль сам дописывает недостающие промежуточные сертификаты в правильном порядке.
    # Для сертификата, подписанного напрямую корневым CA, intermediate_certs можно опустить:
    #   community.crypto.certificate_complete_chain:
    #     path: "{{ crypto_dir }}/{{ service_name }}.crt"
    #     root_certificates: ["{{ crypto_dir }}/ca.crt"]
    #     output: "{{ crypto_dir }}/{{ service_name }}_chain.crt"
    # → changed: [ca_server] => {"changed": true}

    - name: "CSR сервиса с SAN (DNS + IP)"
      community.crypto.openssl_csr:
        path: "{{ crypto_dir }}/{{ service_name }}.csr"
        privatekey_path: "{{ crypto_dir }}/{{ service_name }}.key"
        common_name: "{{ service_name }}"
        subject_alt_name: "DNS:{{ service_name }},DNS:www.{{ service_name }},IP:{{ service_ip }}"
        use_common_name_for_san: false
        mode: "0644"
    # → changed: [ca_server] => {"changed": true, "filename": "/etc/pki/internal/app.example.com.csr"}

    - name: "Выпустить сертификат сервиса, подписанный CA"
      community.crypto.x509_certificate:
        path: "{{ crypto_dir }}/{{ service_name }}.crt"
        csr_path: "{{ crypto_dir }}/{{ service_name }}.csr"
        ownca_path: "{{ crypto_dir }}/ca.crt"
        ownca_privatekey_path: "{{ crypto_dir }}/ca.key"
        ownca_not_after: "{{ cert_validity }}"
        ownca_digest: sha256
        provider: ownca
        mode: "0644"
        backup: true
    # → changed: [ca_server] => {"changed": true, "filename": "/etc/pki/internal/app.example.com.crt", "subject": {...}, "issuer": {...}}
    # повторный запуск: ok: [ca_server] => {"changed": false}

    - name: "Извлечь публичный ключ сервиса"
      community.crypto.openssl_publickey:
        path: "{{ crypto_dir }}/{{ service_name }}.pub"
        privatekey_path: "{{ crypto_dir }}/{{ service_name }}.key"
        mode: "0644"
    # → changed: [ca_server] => {"changed": true, "filename": "/etc/pki/internal/app.example.com.pub"}
```

**Обратите внимание на `subject_alt_name`.** Современные клиенты (браузеры, Go-приложения, systemd) игнорируют CN в пользу SAN. Сертификат с заполненным CN, но пустым SAN, считается невалидным. IP-адрес в SAN указывается с префиксом `IP:`, DNS-имя — с `DNS:`.

### Сценарий 2: Мониторинг срока действия и раннее предупреждение

Проверка сертификата на управляемом хосте без обращения к CA. Параметр `valid_at` принимает словарь «имя → момент времени» и возвращает словарь с теми же именами и булевыми значениями.

```yaml
---
- name: "Проверка срока действия сертификатов"
  hosts: all
  become: true
  tasks:
    - name: "Собрать сведения о сертификате с порогами"
      community.crypto.x509_certificate_info:
        path: /etc/ssl/certs/app.example.com.crt
        valid_at:
          valid_now: "+0s"
          valid_in_30_days: "+30d"
          valid_in_60_days: "+60d"
      register: cert
    # → ok: [host] => {"expired": false, "not_after": "20270418120000Z", "not_before": "20260418000000Z",
    #                 "valid_at": {"valid_now": true, "valid_in_30_days": true, "valid_in_60_days": false},
    #                 "subject": {"commonName": "app.example.com"}, "is_ca": false, "self_signed": false, ...}

    - name: "Определить остаток срока в днях"
      ansible.builtin.set_fact:
        cert_days_left: >-
          {{ ((cert.not_after | to_datetime('%Y%m%d%H%M%SZ') | int)
              - (ansible_facts.epoch | int)) // 86400 }}

    - name: "Упасть, если сертификат истёк или истекает менее чем через 30 дней"
      ansible.builtin.assert:
        that:
          - not cert.expired
          - cert.valid_at.valid_in_30_days
        fail_msg: >-
          Сертификат {{ inventory_hostname }} истекает через
          {{ cert_days_left }} дн. (not_after={{ cert.not_after }}).
          Требуется перевыпуск.
        success_msg: "Сертификат действителен ещё {{ cert_days_left }} дн."
    # → fatal: [host] => {"msg": "Сертификат db01 истекает через 12 дн. (not_after=20270418120000Z). Требуется перевыпуск."}

    - name: "Отправить в метрики Prometheus"
      ansible.builtin.uri:
        url: "http://{{ prometheus_host }}:9091/metrics"
        method: POST
        body_format: text
        body: |
          # TYPE cert_days_remaining gauge
          cert_days_remaining{host="{{ inventory_hostname }}",cert="app.example.com"} {{ cert_days_left }}
        status_code: [200, 201]
      delegate_to: localhost
      when: cert_days_left is defined
      changed_when: false
```

**Второй способ — обход всех сертификатов без падения.** Строгий `assert` останавливает плейбук на первом проблемном хосте, поэтому для инвентаризации соберите факты, а вывод сделайте в конце:

```yaml
- name: "Просканировать сертификаты на всех хостах"
  community.crypto.x509_certificate_info:
    path: "{{ item.path }}"
    valid_at:
      expiring_14d: "+14d"
  loop: "{{ cert_inventory }}"
  loop_control:
    label: "{{ item.name }}"
  register: cert_scan
  failed_when: false

- name: "Собрать список проблемных сертификатов"
  ansible.builtin.set_fact:
    expiring_certs: >-
      {{ cert_scan.results
         | rejectattr('skipped', 'defined')
         | selectattr('expired') | list
         + cert_scan.results
         | rejectattr('skipped', 'defined')
         | rejectattr('valid_at.expiring_14d') | list }}

- name: "Вывести сводку по проблемным сертификатам"
  ansible.builtin.debug:
    msg: "РОТАЦИЯ: {{ item.item.name }} — not_after={{ item.not_after }} (SAN={{ item.subject_alt_name }})"
  loop: "{{ expiring_certs }}"
  loop_control:
    label: "{{ item.item.name }}"

- name: "Отправить уведомление ответственному, если есть проблемные сертификаты"
  ansible.builtin.uri:
    url: "{{ alert_webhook }}"
    method: POST
    body_format: json
    body:
      text: "Требуется перевыпуск {{ expiring_certs | length }} сертификат(ов)"
  when: expiring_certs | length > 0
  changed_when: false
```

Такой подход не прерывает выполнение на первом невалидном сертификате и даёт полную картину по инфраструктуре за один прогон.

### Сценарий 3: Проверка соответствия сертификата требованиям (аудит)

Регулярный контроль: SAN, срок, отсутствие CA-флагов, использование слабого алгоритма подписи.

```yaml
---
- name: "Аудит TLS-сертификатов"
  hosts: web_servers
  become: true
  vars:
    audit_certs:
      - { path: /etc/ssl/certs/app.example.com.crt, expect_san: "dns:app.example.com" }
      - { path: /etc/ssl/certs/api.example.com.crt, expect_san: "dns:api.example.com" }
  tasks:
    - name: "Собрать сведения о сертификатах"
      community.crypto.x509_certificate_info:
        path: "{{ item.path }}"
        valid_at:
          still_valid_30d: "+30d"
      loop: "{{ audit_certs }}"
      loop_control:
        label: "{{ item.path }}"
      register: audit

    - name: "Проверить соответствие требованиям"
      ansible.builtin.assert:
        that:
          # SAN присутствует и содержит ожидаемое имя
          - not item.expired
          - item.valid_at.still_valid_30d
          - item.subject_alt_name | length > 0
          - item.expect_san in item.subject_alt_name
          # сертификат не должен быть CA
          - not item.is_ca
          # слабые алгоритмы подписи запрещены
          - item.signature_algorithm is not search('(md5|sha1)', true)
        fail_msg: >-
          {{ item.item.path }}: SAN={{ item.subject_alt_name }},
          is_ca={{ item.is_ca }}, sig={{ item.signature_algorithm }},
          not_after={{ item.not_after }}
        success_msg: "{{ item.item.path }}: OK"
      loop: "{{ audit.results }}"
      loop_control:
        label: "{{ item.item.path }}"
    # → ok: [web01] => (item=/etc/ssl/certs/app.example.com.crt) => {"changed": false, "msg": "…: OK"}
    # → failed: [web01] => {"msg": "/etc/ssl/certs/api.example.com.crt: SAN=['dns:api.internal'], is_ca=false, sig=sha256WithRSAEncryption, not_after=…"}
```

### Сценарий 4: Экспорт PKCS#12 с паролем из Vault

```yaml
---
- name: "Экспорт сертификата в формате PKCS#12"
  hosts: app_servers
  become: true
  vars:
    p12_password: "{{ vault_app_p12_password }}"
  tasks:
    - name: "Собрать PKCS#12-архив (ключ + сертификат + цепочка)"
      community.crypto.openssl_pkcs12:
        path: /etc/ssl/private/app.example.com.p12
        privatekey_path: /etc/ssl/private/app.example.com.key
        certificate_path: /etc/ssl/certs/app.example.com.crt
        other_certificates:
          - /etc/ssl/certs/ca_bundle.crt
        passphrase: "{{ p12_password }}"
        friendly_name: app.example.com
        mode: "0600"
        backup: true
      no_log: true
    # → changed: [app01] => {"changed": true, "filename": "/etc/ssl/private/app.example.com.p12", "backup_file": "…"}
    # no_log: true подавляет вывод, содержащий содержимое архива

    - name: "Скопировать архив на хост оператора (для импорта в браузер/Keychain)"
      ansible.builtin.fetch:
        src: /etc/ssl/private/app.example.com.p12
        dest: "./artifacts/{{ inventory_hostname }}/app.example.com.p12"
        flat: true
    # → changed: [app01] => {"changed": true, "checksum": "…", "dest": "./artifacts/app01/app.example.com.p12"}
```

**Важно:** модуль возвращает содержимое архива в `pkcs12`. Без `no_log: true` содержимое зашифрованного архива попадёт в лог — это раскрытие защищённого паролем материала и потенциальная утечка метаданных.

### Сценарий 5: Полный жизненный цикл сертификата в одном плейбуке

Ротация по расписанию: проверка → генерация ключа и CSR → выпуск → валидация → безопасное размещение → перезагрузка сервиса.

```yaml
---
- name: "Ротация сертификата при приближении срока"
  hosts: app_servers
  become: true
  serial: 01
  vars:
    pki_host: ca_server
    key_path: /etc/ssl/private/app.example.com.key
    crt_path: /etc/ssl/certs/app.example.com.crt
    ca_path: /etc/ssl/certs/ca_bundle.crt
    renew_before_days: 30

  tasks:
    - name: "Проверить текущий сертификат"
      community.crypto.x509_certificate_info:
        path: "{{ crt_path }}"
        valid_at:
          renew_needed: "+{{ renew_before_days }}d"
      register: current
      failed_when: false

    - name: "Пропустить ротацию, если срок достаточен"
      ansible.builtin.meta: end_host
      when:
        - current is not failed
        - not current.expired
        - current.valid_at.renew_needed
      # Сертификат ещё действителен — ротация не требуется

    - name: "Сохранить резервные копии текущего материала"
      ansible.builtin.copy:
        src: "{{ item.src }}"
        dest: "{{ item.src }}.backup"
        remote_src: true
        mode: "0600"
      loop:
        - { src: "{{ key_path }}" }
        - { src: "{{ crt_path }}" }
      loop_control:
        label: "{{ item.src }}"
      when: current is failed or current.expired or not current.valid_at.renew_needed

    - name: "Сгенерировать новый приватный ключ и CSR"
      community.crypto.openssl_privatekey:
        path: "{{ key_path }}"
        type: ECC
        curve: secp384r1
        mode: "0600"
        regenerate: partial_idempotence
        backup: true
      notify: "Перезапуск сервиса"

    - name: "Сформировать CSR"
      community.crypto.openssl_csr:
        path: /etc/ssl/csr/app.example.com.csr
        privatekey_path: "{{ key_path }}"
        common_name: app.example.com
        subject_alt_name: "DNS:app.example.com,DNS:www.app.example.com,IP:192.0.2.10"
        use_common_name_for_san: false
      notify: "Перезапуск сервиса"

    - name: "Выпустить сертификат на CA-хосте"
      community.crypto.x509_certificate:
        path: /etc/ssl/certs/app.example.com.crt
        csr_path: /etc/ssl/csr/app.example.com.csr
        ownca_path: /etc/pki/internal/ca.crt
        ownca_privatekey_path: /etc/pki/internal/ca.key
        ownca_not_after: "+825d"
        provider: ownca
        mode: "0644"
      delegate_to: "{{ pki_host }}"
      notify: "Перезапуск сервиса"

    - name: "Получить сертификат на app-сервер"
      ansible.builtin.fetch:
        src: /etc/ssl/certs/app.example.com.crt
        dest: "{{ crt_path }}.new"
        flat: true
      delegate_to: "{{ pki_host }}"

    - name: "Проверить новый сертификат до замены действующего"
      community.crypto.x509_certificate_info:
        path: "{{ crt_path }}.new"
        valid_at:
          valid_30d: "+30d"
      register: new_cert

    - name: "Подтвердить корректность нового сертификата"
      ansible.builtin.assert:
        that:
          - not new_cert.expired
          - new_cert.valid_at.valid_30d
          - "'dns:app.example.com' in new_cert.subject_alt_name"
        fail_msg: "Новый сертификат не прошёл проверку — действующий оставлен без изменений"
        success_msg: "Новый сертификат валиден, можно применять"

    - name: "Атомарно заменить сертификат"
      ansible.builtin.command:
        cmd: "mv {{ crt_path }}.new {{ crt_path }}"
      changed_when: true
      notify: "Перезапуск сервиса"

  handlers:
    - name: "Перезапуск сервиса"
      ansible.builtin.systemd:
        name: app.service
        state: reloaded
        daemon_reload: true
```

**Ключевая идея:** новый сертификат проверяется **до** замены действующего. Последовательность «выпустил → развернул → потом увидел, что сломалось» в production недопустима — после неё сервис остаётся с неработающим TLS, пока не откатят вручную.

### Сценарий 6: Выпуск без записи секретов на диск (pipe-модули)

Для сред, где приватный ключ не должен сохраняться на управляемом хосте (агенты, одноразовые контейнеры, tmpfs):

```yaml
- name: "Сгенерировать ключ в памяти и передать в openssl_csr"
  community.crypto.openssl_privatekey_pipe:
    type: ECC
    curve: secp256r1
  register: key_in_memory
  no_log: true

- name: "Сформировать CSR, не записывая ключ на диск"
  community.crypto.openssl_csr:
    path: /dev/shm/app.csr
    privatekey_content: "{{ key_in_memory.privatekey }}"
    common_name: app.example.com
    subject_alt_name: "DNS:app.example.com"
    mode: "0600"
  no_log: true
```

Модули `*_pipe` возвращают содержимое в `privatekey`, `publickey`, `csr`, `certificate`. Они всегда требуют `no_log: true` и теряют преимущества идемпотентности, основанной на файле.

### Сценарий 7: Резервное копирование и восстановление CA (Disaster Recovery)

Для SRE важно иметь возможность быстро восстановить CA после потери хоста. Практика: зашифрованный бэкап ключа и сертификата CA на сетевом файловом хранилище (NFS) или отдельном резервном хосте, с правами `0600` и ограниченным доступом.

```yaml
---
- name: "Бэкап CA на выделенный бэкап-хостов"
  hosts: ca_server
  become: true
  vars:
    ca_dir: /etc/pki/internal
    backup_dir: /mnt/backup/pki
    backup_retention_days: 90
  tasks:
    - name: "Создать каталог для бэкапов"
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: "0700"
        owner: root
        group: root

    - name: "Заархивировать CA-ключ, сертификат и цепочку"
      ansible.builtin.archive:
        path:
          - "{{ ca_dir }}/ca.key"
          - "{{ ca_dir }}/ca.crt"
          - "{{ ca_dir }}/ca_bundle.crt"
        dest: "{{ backup_dir }}/ca_backup_{{ inventory_hostname }}_{{ ansible_date_time.date }}.tar.gz"
        format: gz
        mode: "0600"
      register: ca_backup

    - name: "Удалить бэкапы старше {{ backup_retention_days }} дней"
      ansible.builtin.find:
        paths: "{{ backup_dir }}"
        patterns: "ca_backup_*.tar.gz"
        age: "{{ backup_retention_days }}d"
        age_stamp: mtime
        file_type: file
      register: old_backups

    - name: "Удалить старые бэкапы"
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"
      loop_control:
        label: "{{ item.path }}"

    - name: "Проверить, что архив читается"
      ansible.builtin.command:
        cmd: "tar -tzf {{ ca_backup.dest }}"
      changed_when: false
    # → ok: [ca_server] => {"changed": false, "cmd": "..."}
```

**Восстановление на новом хосте:**

```yaml
---
- name: "Восстановление CA после потери хоста"
  hosts: new_ca_server
  become: true
  vars:
    ca_dir: /etc/pki/internal
    backup_path: /tmp/ca_backup_ca01_20260926.tar.gz
  tasks:
    - name: "Распаковать архив CA"
      ansible.builtin.unarchive:
        src: "{{ backup_path }}"
        dest: "{{ ca_dir }}"
        remote_src: true
        mode: "0600"
        owner: root
        group: root

    - name: "Проверить подпись корневого CA"
      ansible.builtin.command:
        cmd: "openssl verify -CAfile {{ ca_dir }}/ca.crt {{ ca_dir }}/ca.crt"
      changed_when: false
    # → ok: [new_ca_server] => {"changed": false, "stdout": "ca.crt: OK"}

    - name: "Проверить, что ключ соответствует сертификату"
      ansible.builtin.command:
        cmd: "openssl x509 -in {{ ca_dir }}/ca.crt -noout -pubkey | openssl md5; openssl rsa -in {{ ca_dir }}/ca.key -pubout 2>/dev/null | openssl md5"
      changed_when: false
      register: key_match
    # Оба хеша должны совпадать — ключ и сертификат принадлежат одной паре
```

**SRE-рекомендации:**
- Храните бэкап CA на отдельном физическом носителе или в air-gapped хранилище. Скомпрометация CA-ключа = необходимость перевыпуска всей цепочки.
- Включите бэкап в процедуру идемпотентного плейбука; не делайте его ручной операцией.
- Тестируйте восстановление на изолированном стенде не реже одного раза в квартал.
- Для критичных окружений используйте HSM или внешний HSM-совместимый сервис вместо файлового ключа.

## Операции и команды

### Работа с документацией модулей

```bash
# Документация конкретного модуля
ansible-doc community.crypto.openssl_privatekey
ansible-doc community.crypto.x509_certificate

# Список всех модулей коллекции
ansible-doc -l community.crypto

# Только имена модулей
ansible-doc -l community.crypto | awk '/^\s*community\.crypto/ {print $1}'

# Примеры использования из документации
ansible-doc -t module community.crypto.x509_certificate | sed -n '/EXAMPLES/,$p'

# Параметры и значения по умолчанию
ansible-doc community.crypto.x509_certificate | rg -A3 'ownca_not_after|ignore_timestamps|provider'
```

### Ad-hoc команды

```bash
# Генерация приватного ключа (RSA 4096)
ansible app01 -m community.crypto.openssl_privatekey -a "path=/tmp/test.key mode=0600"

# Генерация ECC-ключа на кривой secp384r1
ansible app01 -m community.crypto.openssl_privatekey -a "path=/tmp/ecc.key type=ECC curve=secp384r1"

# Информация о сертификате
ansible app01 -m community.crypto.x509_certificate_info -a "path=/etc/ssl/certs/app.example.com.crt"

# Информация о сертификате с проверкой срока (словарь valid_at в ad-hoc требует JSON)
ansible app01 -m community.crypto.x509_certificate_info -a '{"path": "/etc/ssl/certs/app.example.com.crt", "valid_at": {"expiry_30d": "+30d"}}'

# Проверка, будет ли сертификат перевыпущен (без фактического выпуска)
ansible app01 -b -m community.crypto.x509_certificate -a "path=/etc/ssl/certs/app.example.com.crt csr_path=/etc/ssl/csr/app.example.com.csr ownca_path=/etc/ssl/certs/ca.crt provider=ownca" --check
```

Параметры со словарным типом (`valid_at`, `subject_alt_name`) в ad-hoc требуют передачи всего аргумента как JSON-строки в одинарных кавычках — иначе shell разобьёт аргумент по запятым. В плейбуках эта проблема не возникает.

### Установка и обновление коллекции

```bash
# Установка
ansible-galaxy collection install community.crypto

# Установка конкретной версии
ansible-galaxy collection install community.crypto:3.4.0

# Проверка установленной версии
ansible-galaxy collection list community.crypto

# Обновление
ansible-galaxy collection install community.crypto --upgrade

# Установка в requirements.yml для воспроизводимости
# collections/requirements.yml:
#   - name: community.crypto
#     version: ">=3.0.0,<4.0.0"
ansible-galaxy collection install -r collections/requirements.yml

# Включение коллекции в плейбук
# collections/ansible_collections/requirements.yml то же самое, но
# задаётся через ANSIBLE_COLLECTIONS_PATHS
```

### Установка `cryptography` на управляемые хосты

```yaml
- name: "Установить python3-cryptography на управляемые хосты"
  hosts: all
  become: true
  tasks:
    - name: "Определить диспетчер пакетов и имя пакета cryptography"
      ansible.builtin.package_facts:
        manager: auto

    - name: "Установить python3-cryptography (Debian/Ubuntu или Red Hat)"
      ansible.builtin.package:
        name: "{{ pki_crypto_package }}"
        state: present
      vars:
        pki_crypto_package: >-
          {{
            'python3-cryptography'
            if ansible_facts.os_family in ['Debian', 'Ubuntu']
            else ('python3-cryptography'
                  if ansible_facts.os_family == 'RedHat'
                  else 'python3-crypto')
          }}
```

## Устранение неполадок

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'cryptography'` | Библиотека не установлена на управляемом хосте | Установите `python3-cryptography`/`python3-crypto` на хост, а не на контрольный узел |
| `The mode for the private key file will be 0600` / нет доступа | Каталог закрыт или выставлены права | Проверьте `owner`/`group` каталога, используйте `become: true` |
| `privatekey does not exist` | CSR создан раньше ключа или указан неверный путь | Соблюдайте порядок `openssl_privatekey` → `openssl_csr` |
| `csr does not exist` | Сертификат выпускается до создания CSR | Соблюдайте порядок, проверьте `csr_path` |
| `ownca_path is required for ownca provider` | Не задан сертификат CA | Добавьте `ownca_path` (или `ownca_content`) |
| Ключ перегенерируется при каждом запуске | `regenerate: always` или `force: true` | Используйте `regenerate: partial_idempotence`, добавьте `backup: true` |
| Ключ перегенерирован после смены `size`/`type` | Несовпадение параметров вызывает пересоздание | Понимайте последствия: всё зашифрованное старым ключом станет недоступно. Планируйте смену параметров как отдельную операцию |
| Пароль приватного ключа не подходит | Смена `passphrase` приводит к регенерации | Убедитесь, что `passphrase` берётся из Vault и не меняется между запусками |
| `provider: entrust` не найден | Провайдер удалён в `community.crypto` 3.0.0 | Используйте `acme`, `ownca` или `selfsigned` |
| `to_datetime` падает на `not_after` | Значение в ASN.1 TIME, а не ISO 8601 | Передайте формат явно: `cert.not_after \| to_datetime('%Y%m%d%H%M%SZ')`. Фильтра `asn1time_to_epoch` в коллекции нет |
| `assert` валит плейбук при расхождении SAN | Строгая проверка в `assert` | Для сбора всех нарушений замените `assert` на `debug`/`set_fact` с условием и сводкой в конце |
| `select_crypto_backend` выдаёт предупреждение | Параметр объявлен устаревшим | Удалите параметр: с версии 3.0.0 все значения идентичны, параметр будет удалён в 4.0.0 |
| PKCS#12 не импортируется на клиенте | Неверный порядок в цепочке или устаревший формат | Пересоберите архив с `other_certificates`, включив промежуточные сертификаты |
| `csr signature is not valid` | CSR подписан другим ключом | CSR должен быть подписан тем же ключом, что указан в `privatekey_path` |

### Диагностика

```bash
# Проверить, установлена ли коллекция
ansible-galaxy collection list community.crypto

# Проверить версию cryptography на хосте
ansible app01 -b -m ansible.builtin.command -a "python3 -c 'import cryptography; print(cryptography.__version__)'"

# Проверить права на файлы PKI
ansible app01 -b -m ansible.builtin.stat -a "path=/etc/ssl/private/app.example.com.key"
ansible app01 -b -m ansible.builtin.command -a "ls -la /etc/ssl/private/"

# Полный вывод результата x509_certificate_info
ansible app01 -b -m community.crypto.x509_certificate_info -a "path=/etc/ssl/certs/app.example.com.crt" | python3 -m json.tool

# Проверить, соответствует ли существующий сертификат заданным параметрам
ansible app01 -b -m community.crypto.x509_certificate -a "path=/etc/ssl/certs/app.example.com.crt csr_path=/etc/ssl/csr/app.example.com.csr ownca_path=/etc/ssl/certs/ca.crt provider=ownca" --check --diff

# Проверить цепочку сертификатов
ansible app01 -b -m ansible.builtin.command -a "openssl verify -CAfile /etc/ssl/certs/ca_bundle.crt /etc/ssl/certs/app.example.com.crt"

# Проверить соответствие приватного ключа сертификату
ansible app01 -b -m ansible.builtin.command -a "openssl x509 -in /etc/ssl/certs/app.example.com.crt -noout -pubkey | openssl md5; openssl rsa -in /etc/ssl/private/app.example.com.key -pubout 2>/dev/null | openssl md5"
# Оба хеша должны совпадать

# Проверить содержимое CSR
ansible app01 -b -m ansible.builtin.command -a "openssl req -in /etc/ssl/csr/app.example.com.csr -noout -text"

# Проверить PKCS#12-архив
ansible app01 -b -m ansible.builtin.command -a "openssl pkcs12 -in /etc/ssl/private/app.example.com.p12 -nokeys -passin pass:CHANGEME | openssl x509 -noout -subject -issuer -dates"
```

### Отладка выполнения

```bash
# Максимальная вербальность при выпуске сертификата
ansible-playbook -i inventory.ini pki.yml -vvvv --check --diff

# Отслеживание изменений файлов сертификатов
ansible-playbook -i inventory.ini pki.yml --check --diff -vvv

# Проверить, будет ли изменён сертификат, без выпуска
ansible app01 -b -m community.crypto.x509_certificate -a "path=/etc/ssl/certs/app.example.com.crt ownca_path=/etc/ssl/certs/ca.crt provider=ownca csr_path=/etc/ssl/csr/app.example.com.csr" --check
# ok: [app01] => {"changed": false}   — сертификат соответствует параметрам
# changed: [app01] => {"changed": true, ...}  — параметры различаются, будет выпущен новый
```

## Рекомендации

### Выбор правильного модуля

| Задача | Модуль |
| :--- | :--- |
| Сгенерировать приватный ключ | `community.crypto.openssl_privatekey` |
| Прочитать свойства существующего ключа | `community.crypto.openssl_privatekey_info` |
| Сгенерировать ключ без записи на диск | `community.crypto.openssl_privatekey_pipe` |
| Сменить формат ключа **без** перегенерации | `community.crypto.openssl_privatekey_convert` |
| Создать CSR | `community.crypto.openssl_csr` |
| Проверить подпись и состав CSR | `community.crypto.openssl_csr_info` (или фильтр с тем же именем) |
| Выпустить сертификат | `community.crypto.x509_certificate` |
| Проверить срок, SAN, издателя | `community.crypto.x509_certificate_info` (или фильтр с тем же именем) |
| Сменить формат сертификата PEM/DER | `community.crypto.x509_certificate_convert` |
| Достроить цепочку сертификатов | `community.crypto.certificate_complete_chain` |
| Экспортировать в `.p12` | `community.crypto.openssl_pkcs12` |
| Разобрать существующий `.p12` | `community.crypto.openssl_pkcs12_info` |
| Извлечь ключ и сертификат из `.p12` | `community.crypto.openssl_pkcs12_extract` |
| Получить публичный ключ | `community.crypto.openssl_publickey` |
| Сгенерировать/проверить CRL | `community.crypto.x509_crl` / `x509_crl_info` |
| Параметры Диффи-Хеллмана (legacy) | `community.crypto.openssl_dhparam` |
| Выпустить сертификат через ACME | `community.crypto.acme_certificate` |
| Отозвать сертификат ACME | `community.crypto.acme_certificate_revoke` |
| Получить сертификат, который отдаёт удалённый хост | `community.crypto.get_certificate` |
| SSH-ключи и сертификаты OpenSSH | `community.crypto.openssh_keypair` / `openssh_cert` |
| Управление LUKS-устройствами | `community.crypto.luks_device` |
| Проверить доступные крипто-возможности хоста | `community.crypto.crypto_info` |

### Безопасность

- **Приватные ключи:** права `0600`, владелец `root`, каталог `0700`. Никогда не храните приватные ключи в репозитории.
- **`no_log: true`** обязателен для любой задачи с `passphrase` или `return_content: true`.
- **Пароли и passphrase** — только из Ansible Vault. Не используйте `vars` в открытом виде и не передавайте их через `--extra-vars` в командной строке (они видны в `ps` и в истории shell).
- **CA-ключ** должен находиться на отдельном хосте с ограниченным доступом и не попадать на серверы приложений. Практический приём: `delegate_to` на CA-хост, как в сценарии 5.
- **Минимальный срок действия сертификата** не превышайте разумного: длинный срок увеличивает окно компрометации. Ориентир — 90 дней для публичных, до 2 лет для внутренних.
- **Слабые алгоритмы:** не используйте RSA < 2048 и подпись SHA-1/MD5. Для новых сертификатов предпочитайте ECC (`secp384r1`) — ключ меньше при сопоставимой стойкости.

### Идемпотентность и тестирование

- Всегда задавайте `regenerate: partial_idempotence` и `backup: true` для приватных ключей в production.
- Проверяйте идемпотентность двойным запуском: второй прогон должен вернуть `ok` с `changed: false` для всех задач выпуска.
- Обязательно прогоняйте с `--check --diff` перед применением в production: модули покажут, будет ли сертификат перевыпущен.
- Для сертификатов с относительным сроком (`+825d`) оставляйте `ignore_timestamps: true`, иначе получите бесконечную перевыпуску.
- Храните версию коллекции в `requirements.yml`, а не полагайтесь на версию, установленную в системе: поведение `x509_certificate` менялось между мажорными версиями.

### Производительность и масштабирование

- При массовой ротации (>100 хостов) используйте `async` + `poll` для долгих операций генерации ключей (`openssl_privatekey` с ECC/4096-bit RSA может занимать секунды):
  ```yaml
  - name: "Генерация ключа в фоне"
    community.crypto.openssl_privatekey:
      path: "{{ key_path }}"
      type: RSA
      size: 4096
      mode: "0600"
    async: 300
    poll: 0
  ```
- Используйте `delegate_to` для CA-операций, чтобы не дергать CA-хост 5000 раз. Один `delegate_to`-хост выпускает сертификаты пакетно.
- Для инвентаризации сертификатов на тысячах хостов избегайте `register` на каждой задаче; собирайте факты через `x509_certificate_info` с `failed_when: false` и сводку в конце плейбука.
- Избегайте `return_content: true` в production: он передаёт содержимое ключа/архива через JSON-ответ, что создаёт лишнюю нагрузку на память и увеличивает риск утечки в логи.

### Эксплуатация

- **Ротация по порогу, а не по дате:** проверяйте `valid_at` и запускайте ротацию заранее (за 30 дней), а не в день истечения.
- **Алертинг:** метрика `cert_days_remaining` в Prometheus с порогом 30 дней — стандартный подход; реализация в сценарии 2.
- **Проверяйте SAN, а не CN:** добавление в аудит условия на `subject_alt_name` ловит сертификаты, которые формально выпущены, но не работают в реальных клиентах.
- **Кэшируйте CA-сертификат** в `ca_bundle.crt` и не перевыпускайте его вместе с сертификатами сервисов — иначе придётся обновлять копии на всех хостах.
- **Цепочка доверия:** выпускайте сертификат через промежуточный CA (`ownca_path` указывает на intermediate), чтобы корневой CA можно было держать офлайн.

## Дополнительная информация

- **[Автоматизация сертификатов: Let's Encrypt, Internal CA, ротация](../ansible_certificate_management.md)** — внешние инструменты (certbot, step-ca, HashiCorp Vault PKI), жизненный цикл сертификатов и мониторинг. Этот файл описывает реализацию той же задачи средствами модулей `community.crypto`.
- **[Официальная документация `community.crypto`](https://docs.ansible.com/ansible/latest/collections/community/crypto/index.html)** (анг.) — полный индекс модулей, примеры и руководства.
