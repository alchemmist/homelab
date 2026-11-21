#!/usr/bin/python3
"""Owner-authorized node5 runtime copy. Runs cold only on a different boot ID."""
import datetime,json,os,pathlib,shutil,subprocess,sys
S=pathlib.Path("/var/lib/rancher/k3s/agent/containerd")
D=pathlib.Path("/mnt/files/homelab/runtime/containerd")
R=pathlib.Path("/var/lib/homelab-recovery/runtime-hdd-boot-20261120")
STATE=R/"state.json"

def run(args,timeout=5400,allowed=(0,)):
 p=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
 if p.returncode not in allowed:
  (R/"last-command-error.txt").write_text(p.stderr[-4000:])
  raise RuntimeError("Failed "+args[0]+" exit "+str(p.returncode))
 return p

def save(x):
 t=STATE.with_suffix(".tmp");t.write_text(json.dumps(x,indent=2));t.replace(STATE)
 print(x["phase"],flush=True)

def mount_source(p):return run(["findmnt","-nro","SOURCE","--mountpoint",str(p)]).stdout.strip()

def boot_id():return pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()

def main():
 os.umask(0o077)
 assert os.geteuid()==0
 mode=sys.argv[1]
 if mode=="prepare":
  assert not R.exists() and not D.exists()
  assert S.is_dir() and not S.is_symlink()
  assert mount_source("/mnt/files")=="/dev/sdb1"
  assert shutil.disk_usage("/mnt/files").free>100*1024**3
  R.mkdir(parents=True,mode=0o700)
  D.parent.mkdir(parents=True,exist_ok=True);D.mkdir(mode=0o700)
  shutil.copy2("/etc/fstab",R/"fstab.before")
  x={"phase":"precopy","original_boot_id":boot_id(),"source":str(S),"destination":str(D),"retained_source":str(S)+".ssd-retained-boot-20261120"}
  save(x)
  # Live pre-copy is an optimization, never represented as consistent backup.
  run(["rsync","-aHAXSx","--numeric-ids",str(S)+"/",str(D)+"/"],allowed=(0,24))
  x["phase"]="precopy-complete-needs-new-boot";save(x)
 elif mode=="cold":
  x=json.loads(STATE.read_text())
  if x["phase"]=="hdd-mounted":
   assert mount_source(S)=="/dev/sdb1[/homelab/runtime/containerd]"
   print("Previously switched runtime mount verified",flush=True);return
  assert x["phase"] in ("precopy-complete-needs-new-boot","cold-verify")
  assert boot_id()!=x["original_boot_id"],"Refuse cold copy on the running original boot"
  assert mount_source("/mnt/files")=="/dev/sdb1"
  assert run(["pgrep","-x","containerd"],allowed=(0,1)).returncode==1
  assert run(["pgrep","-x","containerd-shim"],allowed=(0,1)).returncode==1
  assert run(["pgrep","-x","k3s-server"],allowed=(0,1)).returncode==1
  assert run(["mountpoint","-q",str(S)],allowed=(0,1,32)).returncode!=0
  for line in pathlib.Path("/proc/self/mountinfo").read_text().splitlines():
   target=line.split()[4]
   assert target!=str(S) and not target.startswith(str(S)+"/")
  assert str(D)=="/mnt/files/homelab/runtime/containerd" and D.is_dir() and not D.is_symlink()
  if x["phase"]!="cold-verify":
   x["phase"]="cold-final-sync";save(x)
   # Full checksums compare unchanged files; rsync verifies each transferred file.
   # Delete only stale files in our own new staging tree, never source/PVCs.
   run(["rsync","-aHAXSxc","--numeric-ids","--delete",str(S)+"/",str(D)+"/"])
   x["phase"]="cold-verify";save(x)
  # Source is still cold. Check complete metadata/size tree after checksum sync;
  # avoid a redundant second full 50+GiB HDD content read during downtime.
  v=run(["rsync","-aHAXSxni","--numeric-ids","--delete",str(S)+"/",str(D)+"/"])
  (R/"checksum-verification.txt").write_text(v.stdout)
  assert not v.stdout.strip(),"Cold checksum comparison differs"
  os.sync()
  old=pathlib.Path(x["retained_source"]);assert not old.exists()
  x["phase"]="verified-before-mount";save(x)
  S.rename(old);S.mkdir(mode=0o700)
  run(["mount","--bind",str(D),str(S)])
  assert mount_source(S)=="/dev/sdb1[/homelab/runtime/containerd]"
  fstab=pathlib.Path("/etc/fstab");text=fstab.read_text();assert " "+str(S)+" " not in text
  with fstab.open("a") as f:
   f.write("\n# Owner-authorized node5 runtime HDD migration 20261120\n"+str(D)+" "+str(S)+" none bind,x-systemd.requires-mounts-for=/mnt/files 0 0\n");f.flush();os.fsync(f.fileno())
  x["phase"]="hdd-mounted";x["new_boot_id"]=boot_id();save(x)
 else:raise ValueError("Unknown mode")

if __name__=="__main__":main()
