# Установка и применение ArgoCD

ArgoCD - один из популярных инструментов для GitOps'a. Он предоставляет удобный UI для отслеживания приложений, запущенных в кластере k8s, отслеживает рассинхронизацию от git-репозитория настроек, и состояния приложения в кластере и, в зависимости от настроек, автоматически возвращает приложения в желаемое состояние.

Шаги по установке необходимо выполнять на мастер-node‘e кластера k8s:

```bash
ssh sbox.slurm.io
ssh master-1.<uma_nonb3oBaTena> # например, 5000001
sudo -i
```

Склонируйте репозиторий курса и перейдите в директорию `12-lecture/argocd`.

Так как argo использует http/2, дефолтный nginx-ingress-controller с ним несовместим. Поэтому TLS сессия не должна завершаться на nginx'e. Чтобы включить такую возможность, необходимо пропатчить daemonset nginx'a:

```bash
kubectl patch ds -n ingress-nginx nginx-ingress-controller --type='json' -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--enable-ssl-passthrough"}]’
```

Затем нужно отредактировать 12-ю строчку `ingress.yml`, подставив своё имя пользователя вместо: `__SLURM_USERNAME__`

```yaml
- host: argocd.__SLURM_USERNAME__.edu.slurm.io
```

После этого можно запустить argo в кластере:

```bash
kubectl create ns argocd
kubectl apply -f . -n argocd
```

По-умолчанию, пароль администраторской учетной записи устанавливается, как имя пода сервера argo. Его можно вывести на экран следующей командой:

```bash
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server -o name | cut -d/ -f2
```

После чего можно перейти по ссылке `https://argocd.<eawe_ums_none3o8amess>.edu.slurm.io` и авторизоваться на сервере арго с логином `admin` и паролем, полученным выше.

Теперь создайте новый репозиторий и добавьте в него всё содержимое директории `12-lecture/argoapp`. Не забудьте исправить `__SLURM_USERNAME__` в файле `values.yaml`, прежде чем commit'ить изменения.

После этого надо настроить доступ к репозиторию со стороны сервера арго и добавить новый "Application” - т.е. meta-ресурс, описывающий приложение и его git-репозиторий, за которым сервер argo будет следить.

Сначала в меню слева выберите пункт "settings".

Там перейдите к пункту repositories, а затем нажмите кнопку "Connect repo using ssh".
Так же как пользователь должен предъявить ключ, чтобы получить доступ к репо, так и ArgoCD - клиент сервера Gitlab и ему требуется ключ для авторизации.

Обратите внимание: сейчас нам потребуется содержимое приватного ключа:

```bash
if [[ ! -e ~/.ssh/slurm.io_ed25519 ]]; then
  ssh-keygen -t ed25519 -f ~/.ssh/slurm.io_ed25519
fi

if ! grep '.ssh/slurm.io_ed25519' ~/.ssh/config; then
  cat <<EOF >> ~/.ssh/config
Host gitlab.slurm.io
  IdentityFile ~/.ssh/slurm.io_ed25519
  User git
EOF
fi

cat ~/.ssh/slurm.io_ed25519
```

А содержимое публичного ключа (`cat ~/.ssh/slurm.io_ed25519.pub`) нужно добавить в Gitlab: `https://gitlab.slurm.io/profile/keys`

Заполните поля для своего репозитория.

Когда репозиторий будет создан, выберите пункт "Create application” и заполните, как на примере:

*   **Applcation Name**: textserver
*   **Project**: default
*   **SYNC POLICY**: Automatic
*   **SOURCE**: `git@gitlab.slurm.io:s000297/argoapp`
*   **PATH**: .
*   **REVISION**: HEAD
*   **DESTINATION Cluster URL**: `https://kubernetes.default.svc`
*   **Namespace**: textserver

Нажимайте `create` и через некоторое время веб-интерфейс отобразит похожее состояние.

По запросу `curl argoapp.<ваше_имя_пользователя>.edu.slurm.io` получим ответ `Hello from argo!`.

Теперь если изменить 38-ю строку в файле `values.yaml` в созданном репозитории и отправить изменения в git, через некоторое время интерфейс арго сигнализирует, что состояние в кластере больше не синхронизировано с состоянием git-репозитория.

Затем арго исправит расхождения, в чём можно будет убедиться, повторно отправив запрос: `curl argoapp.<ваше_имя_пользователя>.edu.slurm.io`
