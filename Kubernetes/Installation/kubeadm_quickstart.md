# Быстрый старт с kubeadm

## Определения

* **kubeadm**: Официальный инструмент командной строки для простой инициализации (bootstrapping) production-ready кластеров Kubernetes.
* **kubelet**: см. [kubelet](../../Kubernetes/Concepts/control_plane_architecture.md#kubelet)
* **kubectl**: Основной инструмент командной строки для взаимодействия с API-сервером Kubernetes и управления объектами кластера.
* **Bootstrapping**: Процесс первоначальной загрузки и инициализации кластера, включающий развертывание компонентов Control Plane и последующее присоединение узлов.

## Основные концепции

### Жизненный цикл кластера с kubeadm

* **Фокус**: `kubeadm` сфокусирован на командах `init` (создание Control Plane) и `join` (присоединение узлов).
* **Вне зоны ответственности**: `kubeadm` **не занимается** подготовкой инфраструктуры (виртуальных машин, сети), установкой зависимостей (например, Docker) и управлением конфигурацией кластера после его создания.

### Рабочий процесс

1. **Подготовка узлов**: На всех будущих узлах кластера (master и worker) устанавливается среда выполнения контейнеров (например, Docker) и пакеты `kubeadm`, `kubelet`, `kubectl`.
2. **Инициализация master-узла**: На одном из узлов выполняется команда `kubeadm init`. Эта команда развертывает компоненты Control Plane в виде статических подов (`etcd`, `kube-apiserver` и т.д.).
3. **Установка сетевого плагина (CNI)**: Сразу после инициализации необходимо установить CNI-плагин (например, Flannel, Calico), чтобы поды на разных узлах могли общаться друг с другом. Без этого кластер не будет полностью функционален.
4. **Присоединение worker-узлов**: На остальных узлах выполняется команда `kubeadm join` (с токеном, полученным на шаге 2) для их подключения к кластеру.

## Практические сценарии

### Сценарий: Создание одно-мастерного кластера

#### Шаг 1: Подготовка всех узлов (Master и Workers)

1. **Установка среды выполнения контейнеров (Docker)**

    ```bash
    # Установка зависимостей
    sudo apt-get update
    sudo apt-get install -y apt-transport-https ca-certificates curl
    
    # Установка Docker
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ```

2. **Установка инструментов Kubernetes (`kubeadm`, `kubelet`, `kubectl`)**

    ```bash
    # Добавление официального GPG ключа Google Cloud
    sudo curl -fsSLo /usr/share/keyrings/kubernetes-archive-keyring.gpg https://packages.cloud.google.com/apt/doc/apt-key.gpg
    
    # Добавление репозитория Kubernetes
    echo "deb [signed-by=/usr/share/keyrings/kubernetes-archive-keyring.gpg] https://apt.kubernetes.io/ kubernetes-xenial main" | sudo tee /etc/apt/sources.list.d/kubernetes.list
    
    # Установка
    sudo apt-get update
    sudo apt-get install -y kubelet kubeadm kubectl
    
    # Закрепление версий, чтобы избежать случайных обновлений
    sudo apt-mark hold kubelet kubeadm kubectl
    ```

#### Шаг 2: Инициализация Master-узла

1. **Запуск инициализации кластера**
    Команда `kubeadm init` развернет компоненты control-plane. Флаг `--pod-network-cidr` обязателен для большинства сетевых плагинов.

    ```bash
    # Для Flannel используется эта подсеть
    sudo kubeadm init --pod-network-cidr=10.244.0.0/16
    ```

    После успешного выполнения `kubeadm` выведет инструкции по настройке `kubectl` и команду `kubeadm join` с токеном. Сохраните эту команду.

2. **Настройка доступа к кластеру для локального пользователя**

    ```bash
    mkdir -p $HOME/.kube
    sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
    sudo chown $(id -u):$(id -g) $HOME/.kube/config
    ```

#### Шаг 3: Установка сетевого плагина (CNI)

> **Важно:** Кластер не будет полностью функционален (узлы не перейдут в состояние `Ready`) до установки CNI.

```bash
# Установка Flannel
kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml
```

После этого master-узел должен перейти в состояние `Ready`. Проверить: `kubectl get nodes`.

#### Шаг 4: Присоединение Worker-узлов

На **каждой worker-ноде** выполните команду `kubeadm join`, которую вы сохранили на шаге 2.

```bash
# Пример команды
sudo kubeadm join <ip-мастера>:<порт-мастера> --token <токен> --discovery-token-ca-cert-hash sha256:<хэш>
```

После выполнения этой команды узел присоединится к кластеру. Через некоторое время он также должен появиться в выводе `kubectl get nodes` со статусом `Ready`.

## Управление узлами кластера

### Добавление узлов

Процесс добавления узлов различается для Worker и Control-Plane, особенно если первоначальный токен для присоединения истек (по умолчанию он действует 24 часа).

#### Добавление Worker-узла

Это наиболее простой сценарий.

1.  **На master-узле создайте новую команду для присоединения:**
    Эта команда сгенерирует новый токен и выведет полную команду `kubeadm join`, которую нужно будет выполнить на worker-узле.
    ```bash
    sudo kubeadm token create --print-join-command
    ```
2.  **На новом worker-узле выполните полученную команду:**
    Скопируйте и выполните команду из предыдущего шага.
    ```bash
    # Пример команды
    sudo kubeadm join <ip-мастера>:<порт-мастера> --token <токен> --discovery-token-ca-cert-hash sha256:<хэш>
    ```

#### Добавление Control-Plane-узла (при истекшем токене)

Присоединение нового master-узла требует дополнительных шагов для безопасной передачи сертификатов, необходимых для компонентов control-plane и `etcd`.

> **Важно:** В кластере должно быть нечетное количество control-plane узлов (1, 3, 5 и т.д.) для обеспечения кворума `etcd`.

**На существующем master-узле выполните следующие шаги:**

**Шаг 1: Создание нового токена**
```bash
sudo kubeadm token create
# Вывод: <токен> (например, abcdef.0123456789abcdef)
```
Сохраните этот токен.

**Шаг 2: Получение хеша сертификата CA**
Этот хеш нужен, чтобы новый узел мог доверять Certificate Authority кластера.
```bash
openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | openssl rsa -pubin -outform der 2>/dev/null | \
   openssl dgst -sha256 -hex | sed 's/^.* //'
# Вывод: <хэш> (64-символьная строка)
```
Сохраните этот хеш.

**Шаг 3: Загрузка сертификатов в кластер**
Эта команда упаковывает сертификаты (CA, etcd, front-proxy и др.) в `Secret` в `kube-system` и генерирует ключ для их шифрования. Этот ключ потребуется новому узлу для их расшифровки.
```bash
sudo kubeadm init phase upload-certs --upload-certs
# Вывод: <ключ-шифрования-сертификатов> (64-символьная строка)
```
Сохраните этот ключ. Он действителен 2 часа.

**Шаг 4: Формирование и выполнение команды `join` на новом master-узле**

Соберите все полученные данные в одну команду и выполните ее на **новом control-plane узле**.

```bash
sudo kubeadm join <ip-мастера>:<порт> \
  --token <токен_из_шага_1> \
  --discovery-token-ca-cert-hash sha256:<хэш_из_шага_2> \
  --control-plane \
  --certificate-key <ключ_из_шага_3>
```

После выполнения узел присоединится к кластеру как еще одна master-нода.

### Действия после добавления узлов

#### Перераспределение подов CoreDNS
После добавления первых control-plane узлов поды `CoreDNS` могут остаться на одном, самом первом узле. Это создает единую точку отказа для DNS в кластере. Чтобы заставить Kubernetes перераспределить их по разным узлам в соответствии с правилами anti-affinity, выполните перезапуск `Deployment`-а `CoreDNS`.

```bash
kubectl rollout restart deployment coredns -n kube-system
```
Kubernetes плавно остановит старые поды и создаст новые, которые планировщик разместит на разных доступных узлах.

### Удаление узлов

#### Удаление Worker-узла
1.  **Сделать узел недоступным для планирования и удалить с него поды:**
    ```bash
    kubectl drain <имя-worker-узла> --ignore-daemonsets
    ```
2.  **Удалить узел из кластера:**
    ```bash
    kubectl delete node <имя-worker-узла>
    ```
3.  **Сбросить состояние на самом worker-узле:**
    Подключитесь к узлу и выполните:
    ```bash
    sudo kubeadm reset
    ```

#### Удаление Control-Plane узла
Процесс усложняется из-за того, что на control-plane узлах работает кластер `etcd`.

*   **Сценарий 1: Узел доступен (штатное удаление)**
    1.  Выполните `drain` и `delete node`, как для worker-узла.
    2.  На удаляемом узле выполните `sudo kubeadm reset`. Эта команда корректно обработает вывод участника (`member`) из кластера `etcd`.

*   **Сценарий 2: Узел потерян (аварийное удаление)**
    Если узел недоступен, `kubeadm reset` выполнить нельзя. Участник `etcd` останется в кластере в нерабочем состоянии, что может нарушить кворум. Его необходимо удалить вручную.

    1.  **Найти один из рабочих `etcd` подов:**
        ```bash
        kubectl get pods -n kube-system | grep etcd
        ```
        Выберите один из подов, например, `etcd-master-1`.

    2.  **Получить список участников (`members`) кластера `etcd`:**
        Выполните `exec` в рабочий `etcd` под, чтобы использовать `etcdctl`.
        ```bash
        kubectl exec -n kube-system etcd-master-1 -- etcdctl \
          --endpoints=https://127.0.0.1:2379 \
          --cacert=/etc/kubernetes/pki/etcd/ca.crt \
          --cert=/etc/kubernetes/pki/etcd/server.crt \
          --key=/etc/kubernetes/pki/etcd/server.key \
          member list
        ```
        В выводе найдите ID потерянного узла.

    3.  **Удалить участника из кластера `etcd`:**
        Используйте ID из предыдущей команды.
        ```bash
        kubectl exec -n kube-system etcd-master-1 -- etcdctl \
          --endpoints=https://127.0.0.1:2379 \
          --cacert=/etc/kubernetes/pki/etcd/ca.crt \
          --cert=/etc/kubernetes/pki/etcd/server.crt \
          --key=/etc/kubernetes/pki/etcd/server.key \
          member remove <ID_ПОТЕРЯННОГО_УЗЛА>
        ```

    4.  **Удалить объект Node из Kubernetes:**
        ```bash
        kubectl delete node <имя_потерянного_узла>
        ```

### Сброс состояния узла

Для отсоединения узла от кластера и полной очистки всех изменений, сделанных `kubeadm`, используется команда `reset`. Это полезно, если нужно инициализировать узел заново.

```bash
sudo kubeadm reset
```

## Управление сертификатами

`kubeadm` генерирует сертификаты со сроком действия 1 год. Управлять ими можно с помощью встроенных команд.

### Проверка срока действия сертификатов

Эта команда показывает, когда истекает срок действия сертификатов, управляемых `kubeadm`.
```bash
sudo kubeadm certs check-expiration
```
Сертификаты Certificate Authority (`ca.crt`, `etcd/ca.crt`, `front-proxy-ca.crt`) выпускаются на 10 лет и этой командой не обновляются.

### Обновление сертификатов

Команда `renew` позволяет обновить все (`all`) или конкретные сертификаты.

```bash
# Обновить все сертификаты, управляемые kubeadm
sudo kubeadm certs renew all
```

### Применение новых сертификатов

После обновления сертификатов необходимо перезапустить компоненты Control Plane, чтобы они начали использовать новые файлы. Поскольку они работают как статические поды, самый простой способ — временно переместить их манифесты из директории `/etc/kubernetes/manifests/`. `kubelet` удалит поды, а после возвращения манифестов на место — создаст их заново с новыми сертификатами.

1.  **Создать временную директорию:**
    ```bash
    mkdir /tmp/k8s-manifests-backup/
    ```
2.  **Переместить манифесты:**
    ```bash
    sudo mv /etc/kubernetes/manifests/*.yaml /tmp/k8s-manifests-backup/
    ```
3.  **Подождать 15-20 секунд**, пока `kubelet` остановит старые поды.
4.  **Вернуть манифесты обратно:**
    ```bash
    sudo mv /tmp/k8s-manifests-backup/*.yaml /etc/kubernetes/manifests/
    ```
5.  **(Опционально) Перезапустить `kubelet`:**
    Хотя `kubelet` имеет механизм автоматической ротации своих сертификатов (`--rotate-certificates=true`), для надежности можно его перезапустить.
    ```bash
    sudo systemctl restart kubelet
    ```
Эта процедуру можно автоматизировать с помощью `CronJob` в кластере.
