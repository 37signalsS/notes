# 5. Запуск развертывания

Выполните плейбук `cluster.yml` из корневой директории Kubespray, указав путь к вашему inventory.

```bash
# Если вы используете пользователя root для SSH
ansible-playbook -i inventory/my-cluster/inventory.ini cluster.yml

# Если вы используете non-root пользователя с sudo
ansible-playbook -i inventory/my-cluster/inventory.ini --become --user=myuser cluster.yml
```

Процесс установки может занять 15-30 минут.
