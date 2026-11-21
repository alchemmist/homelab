-- Hyprland 0.57+ entry point; keep the rendered host inventory as source.
-- A tty-less compositor may inherit no LANG: tmux then replaces Unicode with underscores.
hl.env('LANG', 'C.UTF-8')
local home=os.getenv('HOME'); local starts={}; local d=hl.dsp
local function trim(s) return s:match('^%s*(.-)%s*$') end
local dirs={l='left',r='right',u='up',d='down'}
local function action(a,v,mouse)
 if a=='exec' then
  if v=='alacritty' then v='alacritty -e tmux -u new-session' end
  if v:match('^hyprctl dispatch movecursor .* && wlogout$') then v='wlogout' end
  return d.exec_cmd(v) elseif a=='killactive' then return d.window.close() elseif a=='exit' then return d.exit() elseif a=='togglefloating' then return d.window.float({action='toggle'}) elseif a=='pseudo' then return d.window.pseudo() elseif a=='fullscreen' then return d.window.fullscreen() elseif a=='layoutmsg' then return d.layout(v) elseif a=='workspace' then return d.focus({workspace=v}) elseif a:match('^movetoworkspace') then return d.window.move({workspace=v,follow=a~='movetoworkspacesilent'}) elseif a=='togglespecialworkspace' then return d.workspace.toggle_special(v) elseif a=='movefocus' then return d.focus({direction=dirs[v]}) elseif a=='swapwindow' then return d.window.swap({direction=dirs[v]}) elseif a=='resizeactive' then local x,y=v:match('(%-?%d+) (%-?%d+)');return d.window.resize({x=tonumber(x),y=tonumber(y)}) elseif a=='movewindow' and mouse then return d.window.drag() elseif a=='resizewindow' then return d.window.resize() elseif a=='togglegroup' then return d.group.toggle() elseif a=='changegroupactive' then return d.group.next() elseif a=='moveoutofgroup' then return d.window.move({out_of_group=true}) end
end
for line in io.lines(home..'/.config/hypr/hyprland.conf') do
 local k,v=line:match('^([%w%-]+)%s*=%s*(.*)'); if v then v=trim(v:gsub('%s+#.*$','')) end
 if k=='monitor' then local o,m,p,s=v:match('([^,]+),%s*([^,]+),%s*([^,]+),%s*(.+)');hl.monitor({output=o,mode=m,position=p,scale=tonumber(s)})
 elseif k=='env' then local n,val=v:match('([^,]+),(.+)');hl.env(n,val)
 elseif k=='exec-once' then if v~='hyprpm reload' then starts[#starts+1]=v end
 elseif k=='bind' or k=='bindm' then local mods,key,a,arg=v:match('^([^,]*),%s*([^,]+),%s*([^,]+),?%s*(.*)$');mods=trim(mods:gsub('%$mainMod','SUPER')):gsub('%s+',' + ');key=trim(key);if key:match('^%d%d%d$') then key='code:'..key end;local act=action(trim(a),arg,k=='bindm');if act then hl.bind((mods~='' and mods..' + ' or '')..key,act,{mouse=k=='bindm'}) end
 elseif k=='windowrule' then local spec={match={}};for token in v:gmatch('[^,]+') do local n,val=trim(token):match('^(%S+)%s+(.+)$');if n and n:match('^match:') then spec.match[n:sub(7)]=val elseif n then spec[n]=val=='on' or val end end;hl.window_rule(spec)
 end
end
hl.config({general={layout='dwindle',border_size=0,gaps_in=8,gaps_out=15},decoration={rounding=15},input={kb_layout='us,ru',kb_options='ctrl:nocaps,grp:shifts_toggle',touchpad={tap_to_click=true}},misc={disable_hyprland_logo=true,disable_splash_rendering=true}})
hl.workspace_rule({workspace='1',monitor='HDMI-A-1',default=true})
hl.window_rule({match={class='^homelab-monitor$'},workspace='1 silent'})
hl.on('hyprland.start',function() for _,cmd in ipairs(starts) do cmd=cmd:gsub('^%[workspace 1 silent%] ','');hl.exec_cmd(cmd) end end)
hl.on('monitor.added',function(m) if m and m.name=='HDMI-A-1' then hl.dispatch(d.workspace.move({workspace='1',monitor='HDMI-A-1'}));hl.exec_cmd('/usr/local/bin/homelab-wallpaper') end end)
