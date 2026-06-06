# Хранение Secret в etcd

## Определения

**etcd** — это высокодоступное распределенное хранилище типа «ключ-значение», используемое Kubernetes в качестве основного хранилища для всех данных кластера (конфигурации, состояния, секретов).

**Хранение секретов в etcd** — процесс сериализации и записи объектов `Secret` в базу данных etcd. По умолчанию данные в etcd записываются в виде обычного текста (сериализованный JSON/Protobuf), где поле `data` закодировано в Base64.

> **Важно:** Base64 не является шифрованием. Любой пользователь, имеющий доступ к файлам etcd или API etcd, может легко декодировать секреты. Для защиты данных необходимо использовать механизм **Encryption at Rest**.

## Основные концепции

### Структура и формат данных

Все секреты в etcd располагаются по определенному пути:
`/registry/secrets/<namespace>/<name>`

*   **Формат:** Protobuf (по умолчанию для внутренних нужд K8s).
*   **Кодировка:** Значения в поле `data` хранятся в Base64.
*   **Ограничение размера:** Лимит etcd на один объект составляет **1 MiB**. Это включает в себя метаданные и само содержимое секрета.

### Шифрование при хранении (Encryption at Rest)

Для обеспечения безопасности данных на диске (в случае кражи бэкапов или доступа к узлам master) API-сервер Kubernetes поддерживает прозрачное шифрование. Шифрование происходит на стороне `kube-apiserver` перед записью в etcd.

**Основные провайдеры шифрования:**

| Провайдер | Описание | Особенности |
| :--- | :--- | :--- |
| **identity** | Без шифрования | Используется по умолчанию. Необходим как fallback при миграции. |
| **aescbc** | AES-CBC с PKCS7 padding | Рекомендуемый стандарт (256-битный ключ). |
| **aesgcm** | AES-GCM | Более современный, обеспечивает проверку целостности, но требует больше ресурсов CPU. |
| **kms** | Внешний KMS (Key Management Service) | Самый безопасный метод. Интеграция с AWS KMS, Google KMS, Vault. Ключи хранятся вне кластера. |

## Практические сценарии

### Просмотр данных напрямую в etcd (etcdctl)

Для отладки или аудита можно прочитать данные непосредственно из etcd, используя утилиту `etcdctl`. Для этого требуются сертификаты доступа.

```bash
# Настройка переменных окружения для etcdctl
export ETCDCTL_API=3
ENDPOINT="https://127.0.0.1:2379"
CACERT="/etc/kubernetes/pki/etcd/ca.crt"
CERT="/etc/kubernetes/pki/etcd/server.crt"
KEY="/etc/kubernetes/pki/etcd/server.key"

# Получение сырых данных секрета (будут видны как Base64 или зашифрованные данные)
etcdctl --endpoints=$ENDPOINT --cacert=$CACERT --cert=$CERT --key=$KEY \
  get /registry/secrets/default/my-secret
```

### Настройка EncryptionConfiguration

Для включения шифрования создайте файл конфигурации и передайте его API-серверу через флаг `--encryption-provider-config`.

```yaml
# /etc/kubernetes/encryption-config.yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
      - configmaps # Рекомендуется шифровать и ConfigMap, если там есть токены
    providers:
      - aescbc:
          keys:
            - name: key1
              secret: <base64-encoded-32-byte-key> # echo -n "your-32-byte-key-here" | base64
      - identity: {} # Позволяет читать старые (незашифрованные) данные
```

**Применение:** Добавьте флаг в манифест Static Pod API-сервера (`/etc/kubernetes/manifests/kube-apiserver.yaml`):
`--encryption-provider-config=/etc/kubernetes/encryption-config.yaml`

### Ротация ключей шифрования

Для смены ключа добавьте новый ключ **первым** в список провайдеров.

1.  Обновите `EncryptionConfiguration`:
    ```yaml
    providers:
      - aescbc:
          keys:
            - name: key2 # Новый основной ключ
              secret: <new-base64-key>
            - name: key1 # Старый ключ для расшифровки существующих данных
              secret: <old-base64-key>
    ```
2.  Перезапустите API-сервер.
3.  Перезапишите все секреты, чтобы они зашифровались новым ключом:
    ```bash
    kubectl get secrets --all-namespaces -o json | kubectl replace -f -
    ```

## Дополнительная информация

### Ограничения и нюансы

*   **Производительность:** Шифрование добавляет небольшую задержку при операциях чтения/записи в API-сервер.
*   **Безопасность конфигурации:** Сам файл `EncryptionConfiguration` содержит секретные ключи. Он должен быть защищен правами доступа (только для root) на уровне ОС.
*   **Бэкапы:** При резервном копировании etcd убедитесь, что вы также сохраняете файл конфигурации шифрования, иначе восстановить данные будет невозможно.

### Связанные темы

[Основы Secret](secrets_basics.md), [Безопасность Secret](security.md), [Внешние менеджеры](external_managers.md), [Шифрование etcd в Concepts](../../Concepts/etcd_alternatives_and_security.md).
