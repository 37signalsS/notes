# Присоединение узлов к HA кластеру

## Определения

**kubeadm join** — команда для расширения кластера путём присоединения новых узлов (как мастеров, так и воркеров) к существующей среде.

**Bootstrap Token** — временный секрет, используемый для аутентификации узла при первом подключении к кластеру. По умолчанию имеет срок жизни (TTL) 24 часа.

**Control Plane Endpoint** — стабильная точка входа (VIP или DNS-имя балансировщика), через которую узлы обращаются к API-серверу кластера.

---

## Основные концепции

### Процесс и механизмы присоединения

Присоединение узлов — это многоэтапный процесс, который выполняется после [инициализации Control Plane](../kubeadm/cluster_initialization.md) первого узла.

1.  **Аутентификация**: Узел использует Bootstrap Token для проверки подлинности в API-сервере.
2.  **Проверка сертификатов**: Узел получает CA-сертификат кластера и проверяет его соответствие через хэш (`discovery-token-ca-cert-hash`).
3.  **Конфигурация Kubelet**: `kubeadm` генерирует локальные конфигурационные файлы для `kubelet` и запускает его.
4.  **Регистрация**: Узел регистрируется в API-сервере, после чего на него назначаются системные компоненты (kube-proxy, CNI).

**Типы узлов:**
- **Control Plane (Мастера)**: Присоединяются с флагом `--control-plane`. Требуют наличия сертификатов кластера (через `--certificate-key` или копирование вручную).
- **Worker (Воркеры)**: Присоединяются без специальных флагов. Выполняют только рабочие нагрузки.

Подробнее об архитектуре — в [руководстве по инициализации кластера](../kubeadm/cluster_initialization.md).

---

## Практические сценарии

### Шаг 7: Присоединение дополнительных мастер-узлов

На **втором и третьем** мастер-узлах выполните команду, полученную при инициализации первого мастера.

**Требования:**
- Балансировщик нагрузки должен быть доступен по адресу `LOAD_BALANCER_VIP:6443`.
- Порты `6443`, `2379-2380` (для etcd), `10250` должны быть открыты.

```bash
sudo kubeadm join LOAD_BALANCER_VIP:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

**Разбор параметров**:
- `--control-plane` — указывает, что узел будет частью управляющего слоя.
- `--certificate-key` — ключ для расшифровки сертификатов, загруженных в секреты кластера во время `kubeadm init --upload-certs`.
- `--cri-socket` — путь к сокету среды выполнения контейнеров (для containerd обязателен в случае нескольких сред).

**Результат**:
- Узел добавится в кластер etcd.
- Запустятся статические поды `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`.
- На узел будет наложен Taint `node-role.kubernetes.io/control-plane:NoSchedule`.

### Шаг 8: Присоединение worker-узлов

Если Bootstrap Token истёк (прошло >24 часов), сгенерируйте новую команду на любом исправном мастере:

```bash
# Генерация команды присоединения с новым токеном
kubeadm token create --print-join-command
```

**Выполнение на каждом worker-узле:**

```bash
sudo kubeadm join LOAD_BALANCER_VIP:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

> **Примечание:** Worker-узлы не требуют доступа к сертификатам через `--certificate-key`, так как они не запускают компоненты управляющего слоя.

---

### Шаг 9: Мониторинг процесса присоединения

Следите за состоянием узлов с мастер-ноды:

```bash
# Наблюдение в реальном времени
kubectl get nodes -w
```

**Типичный жизненный цикл статуса:**
1.  `NotReady` — узел зарегистрирован, но сетевой плагин (CNI) ещё не запущен.
2.  `Ready` — Calico/Flannel развёрнут, узел готов принимать нагрузку.

**Ожидаемый вид списка узлов (Kubernetes v1.35.x):**

```text
NAME       STATUS   ROLES           AGE   VERSION
k8s-m1     Ready    control-plane   60m   v1.35.x
k8s-m2     Ready    control-plane   15m   v1.35.x
k8s-m3     Ready    control-plane   14m   v1.35.x
k8s-w1     Ready    <none>          5m    v1.35.x
```

---

### Шаг 10: Верификация и детальная проверка

Для глубокого анализа состояния узла используйте:

```bash
# Подробная информация о ресурсах, taints и условиях (Conditions)
kubectl describe node k8s-w1
```

**Проверка системных компонентов:**

```bash
# Убедитесь, что kube-proxy и CNI запущены на всех узлах
kubectl get pods -n kube-system -o wide | grep -E 'kube-proxy|calico-node'
```

**Проверка связности etcd (на мастерах):**

```bash
# Проверка кворума и списка участников кластера etcd
sudo kubectl exec -n kube-system etcd-k8s-m1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status --cluster -w table
```

---

## Дополнительная информация

### Углублённая отладка

Если команда `kubeadm join` зависает или завершается ошибкой:

1.  **Проверка логов kubelet**:
    ```bash
    sudo journalctl -u kubelet -f
    ```
2.  **Проверка доступности API через VIP**:
    ```bash
    curl -k https://LOAD_BALANCER_VIP:6443/healthz
    # Должно вернуть: ok
    ```
3.  **Сброс состояния при неудаче**:
    ```bash
    sudo kubeadm reset -f
    sudo rm -rf /etc/cni/net.d
    sudo iptables -F && sudo iptables -t nat -F && sudo iptables -t mangle -F && sudo iptables -X
    ```

### Управление Bootstrap токенами

| Команда | Описание |
| :--- | :--- |
| `kubeadm token list` | Список активных токенов и их TTL |
| `kubeadm token create --ttl 1h` | Создать временный токен на 1 час |
| `kubeadm init phase upload-certs --upload-certs` | Повторная загрузка сертификатов для новых мастеров |

### Типичные проблемы Bare Metal

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `CA hash mismatch` | Изменился CA сертификат | Получить актуальный хэш: `openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | openssl rsa -pubin -outform der 2>/dev/null | openssl dgst -sha256 -hex` |
| `ETCD_JOIN_ERROR` | Проблемы сети между мастерами | Проверить порты `2379-2380` и время (drift) между узлами |
| `CRI contact error` | Неверный сокет в конфиге | Явно указать `--cri-socket` или проверить статус `containerd` |

### Интеграция с процессом развёртывания

Присоединение узлов — **завершающий этап физического развёртывания** (шаги 7–8). Далее следуют этапы настройки [хранилищ (StorageClass)](../../Storage/storageclass.md) и [Ingress-контроллеров](../../Networking/Ingress/overview.md).

Полный цикл проверки работоспособности описан в [руководстве по верификации](./k8s_ha_cluster_verification.md).
