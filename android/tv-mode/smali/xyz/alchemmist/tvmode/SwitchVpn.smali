.class Lxyz/alchemmist/tvmode/SwitchVpn;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;

.field final activity:Landroid/app/Activity;
.field final youtube:Z
.field handler:Landroid/os/Handler;
.field phase:I
.field deadline:J

.method constructor <init>(Landroid/app/Activity;Z)V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    iput-object p1, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    iput-boolean p2, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->youtube:Z

    return-void
.end method

.method start()V
    .locals 3

    new-instance v0, Landroid/os/Handler;

    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;
    move-result-object v1

    invoke-direct {v0, v1}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V
    iput-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->handler:Landroid/os/Handler;

    const/4 v0, 0x0
    iput v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->phase:I

    invoke-virtual {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->run()V

    return-void
.end method

.method private activeVpn()Z
    .locals 4

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;

    const-string v1, "connectivity"
    invoke-virtual {v0, v1}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Landroid/net/ConnectivityManager;

    invoke-virtual {v0}, Landroid/net/ConnectivityManager;->getActiveNetwork()Landroid/net/Network;
    move-result-object v1
    if-eqz v1, :no_vpn

    invoke-virtual {v0, v1}, Landroid/net/ConnectivityManager;->getNetworkCapabilities(Landroid/net/Network;)Landroid/net/NetworkCapabilities;
    move-result-object v0
    if-eqz v0, :no_vpn

    const/4 v1, 0x4
    invoke-virtual {v0, v1}, Landroid/net/NetworkCapabilities;->hasTransport(I)Z
    move-result v0
    return v0

    :no_vpn
    const/4 v0, 0x0
    return v0
.end method

.method private vpnReady()Z
    .locals 4

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    const-string v1, "connectivity"
    invoke-virtual {v0, v1}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Landroid/net/ConnectivityManager;

    invoke-virtual {v0}, Landroid/net/ConnectivityManager;->getActiveNetwork()Landroid/net/Network;
    move-result-object v1
    if-eqz v1, :not_ready

    invoke-virtual {v0, v1}, Landroid/net/ConnectivityManager;->getNetworkCapabilities(Landroid/net/Network;)Landroid/net/NetworkCapabilities;
    move-result-object v0
    if-eqz v0, :not_ready

    const/4 v1, 0x4
    invoke-virtual {v0, v1}, Landroid/net/NetworkCapabilities;->hasTransport(I)Z
    move-result v1
    if-eqz v1, :not_ready

    const/16 v1, 0x10
    invoke-virtual {v0, v1}, Landroid/net/NetworkCapabilities;->hasCapability(I)Z
    move-result v0
    return v0

    :not_ready
    const/4 v0, 0x0
    return v0
.end method

.method private wireguardMarked()Z
    .locals 3

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    invoke-virtual {v0}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0

    const-string v1, "always_on_vpn_app"
    invoke-static {v0, v1}, Landroid/provider/Settings$Secure;->getString(Landroid/content/ContentResolver;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0

    const-string v1, "com.wireguard.android"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    return v0
.end method

.method private targetPresent()Z
    .locals 2

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->activeVpn()Z
    move-result v0
    if-eqz v0, :no

    iget-boolean v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->youtube:Z
    if-eqz v0, :grafana

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->wireguardMarked()Z
    move-result v0
    if-nez v0, :no

    const/4 v0, 0x1
    return v0

    :grafana
    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->wireguardMarked()Z
    move-result v0
    return v0

    :no
    const/4 v0, 0x0
    return v0
.end method

.method private targetActive()Z
    .locals 2

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->vpnReady()Z
    move-result v0
    if-eqz v0, :not_ready

    iget-boolean v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->youtube:Z
    if-eqz v0, :grafana

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->wireguardMarked()Z
    move-result v0
    if-nez v0, :not_ready

    const/4 v0, 0x1
    return v0

    :grafana
    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->wireguardMarked()Z
    move-result v0
    return v0

    :not_ready
    const/4 v0, 0x0
    return v0
.end method

.method private setWireguardAlwaysOn()V
    .locals 4

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    invoke-virtual {v0}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0

    const-string v1, "always_on_vpn_app"
    const-string v2, "com.wireguard.android"
    invoke-static {v0, v1, v2}, Landroid/provider/Settings$Secure;->putString(Landroid/content/ContentResolver;Ljava/lang/String;Ljava/lang/String;)Z

    const-string v1, "always_on_vpn_lockdown"
    const/4 v2, 0x0
    invoke-static {v0, v1, v2}, Landroid/provider/Settings$Secure;->putInt(Landroid/content/ContentResolver;Ljava/lang/String;I)Z

    return-void
.end method

.method private clearAlwaysOn()V
    .locals 3

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    invoke-virtual {v0}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0

    const-string v1, "always_on_vpn_app"
    const/4 v2, 0x0
    invoke-static {v0, v1, v2}, Landroid/provider/Settings$Secure;->putString(Landroid/content/ContentResolver;Ljava/lang/String;Ljava/lang/String;)Z

    const-string v1, "always_on_vpn_lockdown"
    invoke-static {v0, v1, v2}, Landroid/provider/Settings$Secure;->putInt(Landroid/content/ContentResolver;Ljava/lang/String;I)Z

    return-void
.end method

.method private sendWireguard(Z)V
    .locals 4

    new-instance v0, Landroid/content/Intent;

    if-eqz p1, :down_action
    const-string v1, "com.wireguard.android.action.SET_TUNNEL_UP"
    goto :action_ready

    :down_action
    const-string v1, "com.wireguard.android.action.SET_TUNNEL_DOWN"

    :action_ready
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    const-string v1, "com.wireguard.android"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->setPackage(Ljava/lang/String;)Landroid/content/Intent;

    const-string v1, "tunnel"
    const-string v2, "xiaomi-tv"
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    iget-object v1, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    invoke-virtual {v1, v0}, Landroid/content/Context;->sendBroadcast(Landroid/content/Intent;)V

    return-void
.end method

.method private sendHapp(Ljava/lang/String;)V
    .locals 4

    new-instance v0, Landroid/content/Intent;
    const-string v1, "android.intent.action.VIEW"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    invoke-static {p1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/content/Intent;->setData(Landroid/net/Uri;)Landroid/content/Intent;

    const-string v1, "su.happ.proxyutility"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->setPackage(Ljava/lang/String;)Landroid/content/Intent;

    const/high16 v1, 0x10000000
    invoke-virtual {v0, v1}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;

    iget-object v1, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    invoke-virtual {v1, v0}, Landroid/content/Context;->startActivity(Landroid/content/Intent;)V

    return-void
.end method

.method private launchDestination()V
    .locals 4

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    new-instance v1, Landroid/content/Intent;
    invoke-direct {v1}, Landroid/content/Intent;-><init>()V

    iget-boolean v2, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->youtube:Z
    if-eqz v2, :open_fully

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->closeFully()V

    const-string v2, "com.google.android.youtube.tv"
    const-string v3, "com.google.android.apps.youtube.tv.activity.ShellActivity"
    invoke-virtual {v1, v2, v3}, Landroid/content/Intent;->setClassName(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    goto :start_destination

    :open_fully
    const-string v2, "de.ozerov.fully"
    const-string v3, "de.ozerov.fully.FullyActivity"
    invoke-virtual {v1, v2, v3}, Landroid/content/Intent;->setClassName(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    :start_destination
    const/high16 v2, 0x10000000
    invoke-virtual {v1, v2}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;
    invoke-virtual {v0, v1}, Landroid/app/Activity;->startActivity(Landroid/content/Intent;)V
    invoke-virtual {v0}, Landroid/app/Activity;->finish()V

    return-void
.end method

.method private closeFully()V
    .locals 3

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    const-string v1, "activity"
    invoke-virtual {v0, v1}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Landroid/app/ActivityManager;

    const-string v1, "de.ozerov.fully"
    invoke-virtual {v0, v1}, Landroid/app/ActivityManager;->killBackgroundProcesses(Ljava/lang/String;)V

    return-void
.end method

.method private schedule()V
    .locals 3

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->handler:Landroid/os/Handler;
    const-wide/16 v1, 0x1f4
    invoke-virtual {v0, p0, v1, v2}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z

    return-void
.end method

.method public run()V
    .locals 7

    iget v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->phase:I
    if-nez v0, :poll_disconnect

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->targetPresent()Z
    move-result v0
    if-eqz v0, :not_already_target

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->targetActive()Z
    move-result v0
    if-nez v0, :already_target_ready

    const/4 v0, 0x2
    iput v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->phase:I
    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v0
    const-wide/16 v2, 0x7530
    add-long/2addr v0, v2
    iput-wide v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->deadline:J
    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->schedule()V
    return-void

    :already_target_ready
    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->launchDestination()V
    return-void

    :not_already_target
    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->activeVpn()Z
    move-result v0
    if-eqz v0, :begin_connect

    iget-boolean v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->youtube:Z
    if-eqz v0, :disconnect_happ

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->clearAlwaysOn()V
    const/4 v0, 0x0
    invoke-direct {p0, v0}, Lxyz/alchemmist/tvmode/SwitchVpn;->sendWireguard(Z)V
    goto :wait_for_disconnect

    :disconnect_happ
    const-string v0, "happ://disconnect_without_ui"
    invoke-direct {p0, v0}, Lxyz/alchemmist/tvmode/SwitchVpn;->sendHapp(Ljava/lang/String;)V

    :wait_for_disconnect
    const/4 v0, 0x1
    iput v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->phase:I

    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v0
    const-wide/16 v2, 0x3a98
    add-long/2addr v0, v2
    iput-wide v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->deadline:J

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->schedule()V
    return-void

    :begin_connect
    iget-boolean v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->youtube:Z
    if-eqz v0, :connect_wireguard

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->clearAlwaysOn()V
    const-string v0, "happ://connect_without_ui"
    invoke-direct {p0, v0}, Lxyz/alchemmist/tvmode/SwitchVpn;->sendHapp(Ljava/lang/String;)V
    goto :connect_started

    :connect_wireguard
    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->setWireguardAlwaysOn()V
    const/4 v0, 0x1
    invoke-direct {p0, v0}, Lxyz/alchemmist/tvmode/SwitchVpn;->sendWireguard(Z)V

    :connect_started
    const/4 v0, 0x2
    iput v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->phase:I

    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v0
    const-wide/16 v2, 0x7530
    add-long/2addr v0, v2
    iput-wide v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->deadline:J

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->schedule()V
    return-void

    :poll_disconnect
    const/4 v1, 0x1
    if-ne v0, v1, :poll_connect

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->activeVpn()Z
    move-result v0
    if-eqz v0, :begin_connect
    goto :check_deadline

    :poll_connect
    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->targetActive()Z
    move-result v0
    if-eqz v0, :check_deadline

    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->launchDestination()V
    return-void

    :check_deadline
    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v0
    iget-wide v2, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->deadline:J
    cmp-long v4, v0, v2
    if-ltz v4, :retry

    iget-object v0, p0, Lxyz/alchemmist/tvmode/SwitchVpn;->activity:Landroid/app/Activity;
    invoke-virtual {v0}, Landroid/app/Activity;->finish()V
    return-void

    :retry
    invoke-direct {p0}, Lxyz/alchemmist/tvmode/SwitchVpn;->schedule()V

    return-void
.end method
