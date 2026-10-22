.class public Lxyz/alchemmist/tvmode/GrafanaActivity;
.super Landroid/app/Activity;

.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Landroid/app/Activity;-><init>()V

    return-void
.end method

.method public onCreate(Landroid/os/Bundle;)V
    .locals 2

    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V

    new-instance v0, Lxyz/alchemmist/tvmode/SwitchVpn;

    const/4 v1, 0x0
    invoke-direct {v0, p0, v1}, Lxyz/alchemmist/tvmode/SwitchVpn;-><init>(Landroid/app/Activity;Z)V

    invoke-virtual {v0}, Lxyz/alchemmist/tvmode/SwitchVpn;->start()V

    return-void
.end method
