# Управление сертификатами Kubernetes через kubeadm

## Определения

**kubeadm** — стандартная утилита управления жизненным циклом кластера, предоставляющая инструменты для выпуска, проверки и продления сертификатов Control Plane.

**CA (Certificate Authority)** — доверенный центр сертификации. Kubernetes использует несколько независимых CA (для API-сервера, etcd и front-proxy) для реализации принципа наименьших привилегий. Подробнее: [Обзор PKI](../../Security/Concepts/pki_overview.md).

**Leaf Certificates (Листовые сертификаты)** — сертификаты конечных компонентов (например, `apiserver`), подписанные соответствующим CA.

**CSR (Certificate Signing Request)** — запрос на подпись сертификата. Используется компонентами (особенно Kubelet) для получения или обновления своих сертификатов через API-сервер.

**Admin kubeconfig** — файл `/etc/kubernetes/admin.conf`, содержащий клиентский сертификат пользователя `kubernetes-admin`. По умолчанию срок его действия также составляет 1 год.

### Ключевые сертификаты Control Plane

Все сертификаты и ключи по умолчанию хранятся в директории `/etc/kubernetes/pki`.

| Файл сертификата | Назначение | Кем подписан |
| :--- | :--- | :--- |
| **ca.crt** | Основной корневой CA кластера | Self-signed |
| **apiserver.crt** | Сертификат сервера API (порт 6443) | ca.crt |
| **apiserver-kubelet-client.crt** | Клиентский сертификат API → Kubelet | ca.crt |
| **front-proxy-ca.crt** | CA для агрегированного API-слоя | Self-signed |
| **front-proxy-client.crt** | Клиент для агрегированного API | front-proxy-ca.crt |
| **etcd/ca.crt** | Корневой CA для кластера etcd | Self-signed |
| **etcd/server.crt** | Сертификат узла etcd | etcd/ca.crt |
| **etcd/peer.crt** | Для взаимодействия узлов etcd между собой | etcd/ca.crt |
| **apiserver-etcd-client.crt** | Клиентский сертификат API → etcd | etcd/ca.crt |

## Основные концепции

### Сроки действия и ротация

| Тип сертификата | Срок действия | Способ обновления |
| :--- | :--- | :--- |
| **Корневые CA** | 10 лет | Ручная ротация (сложный процесс) |
| **Сертификаты компонентов** | 1 год | Автоматически (при `upgrade`) или `renew` |
| **Admin kubeconfig** | 1 год | Автоматически (при `upgrade`) или `renew` |
| **Kubelet client** | 1 год | Автоматическая ротация (при включенном `rotateCertificates`) |

> **Важно:** Обновление версии Kubernetes через `kubeadm upgrade` автоматически продлевает все сертификаты, управляемые kubeadm. Если вы не планируете обновлять версию кластера до истечения года, необходимо выполнить ручное продление.

### Version Skew и совместимость

Утилита `kubeadm` должна соответствовать версии API-сервера. Не рекомендуется использовать `kubeadm` более новой версии, чем текущий Control Plane, для управления его сертификатами.

### Настройка сроков (v1.31+, v1beta4 API)

В современных версиях kubeadm можно переопределить сроки действия через `ClusterConfiguration`:

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
certificateValidityPeriod: 8760h      # Листовые сертификаты (1 год)
caCertificateValidityPeriod: 87600h   # CA сертификаты (10 лет)
```

## Практические сценарии

Все команды должны выполняться под учетной записью `root` на узлах Control Plane.

### Проверка срока действия

```bash
sudo kubeadm certs check-expiration
```
Команда анализирует файлы в `/etc/kubernetes/pki` и конфигурационные файлы в `/etc/kubernetes/*.conf`.

### Ручное продление всех сертификатов

Если до истечения срока осталось мало времени:

```bash
sudo kubeadm certs renew all
```
После выполнения этой команды сертификаты обновляются на диске, но **работающие компоненты (API-сервер, etcd) продолжают использовать старые сертификаты в памяти**.

### Применение обновленных сертификатов

Чтобы изменения вступили в силу, необходимо перезапустить статические поды Control Plane:

1. **Автоматический способ:** Kubelet обычно замечает изменение файлов в `/etc/kubernetes/manifests` и перезапускает поды.
2. **Гарантированный способ:**
   ```bash
   sudo systemctl restart kubelet
   ```
3. **Принудительный способ (через временное перемещение):**
   ```bash
   sudo mv /etc/kubernetes/manifests/*.yaml /tmp/
   sleep 20
   sudo mv /tmp/*.yaml /etc/kubernetes/manifests/
   ```

### Ротация сертификатов в HA-кластерах

В кластерах с несколькими мастерами (High Availability):
1. Продление сертификатов должно быть выполнено **на каждом узле Control Plane** независимо.
2. Сертификаты `ca.crt`, `etcd/ca.crt` и `front-proxy-ca.crt` должны быть **идентичны** на всех узлах. Если вы решите сменить CA, его нужно скопировать на все узлы вручную.

### Обновление Admin Kubeconfig

После `kubeadm certs renew all` сертификат внутри `/etc/kubernetes/admin.conf` обновляется. Если вы используете копию этого файла в `~/.kube/config`, её нужно обновить:

```bash
sudo cp /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

### Добавление новых Subject Alternative Names (SANs)

Если вам нужно добавить новый IP или DNS-имя (например, адрес внешнего балансировщика) в сертификат API-сервера:

1. Отредактируйте `kubeadm-config` ConfigMap:
   ```bash
   kubectl edit cm kubeadm-config -n kube-system
   ```
   Добавьте в `ClusterConfiguration`:
   ```yaml
   apiServer:
     certSANs:
     - "1.2.3.4"
     - "api.example.com"
   ```
2. Удалите текущий сертификат:
   ```bash
   sudo rm /etc/kubernetes/pki/apiserver.{crt,key}
   ```
3. Сгенерируйте его заново:
   ```bash
   sudo kubeadm init phase certs apiserver --config /path/to/local/config.yaml
   ```

### Ротация сертификатов Kubelet (Server TLS Bootstrap)

По умолчанию Kubelet использует сертификаты, выписанные при инициализации. Для включения автоматической ротации серверных сертификатов:

1. В `KubeletConfiguration` установите:
   ```yaml
   serverTLSBootstrap: true
   ```
2. После перезапуска Kubelet создаст CSR. Проверьте их:
   ```bash
   kubectl get csr
   ```
3. Одобрите запрос:
   ```bash
   kubectl certificate approve <csr-name>
   ```

## Диагностика и устранение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **x509: certificate has expired** | Срок действия истек | Выполнить `renew all` и перезапустить компоненты. |
| **Unable to connect to the server: x509...** | Истек клиентский сертификат в kubeconfig | Обновить `admin.conf` и скопировать его в `~/.kube/config`. |
| **etcd connection refused (TLS error)** | Несовпадение CA или истечение `apiserver-etcd-client` | Проверить целостность `/etc/kubernetes/pki/etcd/ca.crt` на всех узлах. |
| **Расхождение времени на узлах** | Сертификат "еще не валиден" или "уже истек" | Настройте синхронизацию времени через `ntp` или `chrony`. |

## Дополнительная информация

### Лучшие практики

* **Мониторинг:** Используйте Prometheus Blackbox Exporter или специализированные скрипты для проверки срока действия сертификата на порту 6443.
* **Резервное копирование:** Делайте бэкап директории `/etc/kubernetes/pki` раз в месяц и перед каждым обновлением.
* **ServiceAccount Keys:** Файлы `sa.key` и `sa.pub` — это ключи для подписи JWT-токенов, они не имеют срока действия и не проверяются командой `check-expiration`.

### Ограничения

* `kubeadm` не управляет сертификатами, если кластер был развернут с использованием внешнего CA (External CA).
* Автоматическое продление через `kubeadm upgrade` работает только для сертификатов, расположенных в стандартных путях.

### Связанные темы

* [Предотвращение истечения SSL](./ssl_expiration_prevention.md) — общая стратегия мониторинга.
* [Обновление кластера](./upgrading_clusters.md) — автоматическая ротация в процессе апгрейда.
* [Обзор PKI в Kubernetes](../../Security/Concepts/pki_overview.md) — глубокое понимание иерархии доверия.
* [SSL/TLS в Nginx](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_best_practices.md) — если API-сервер проксируется через Nginx.
