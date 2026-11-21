"""Native Agent Server child launcher. Install in private operator tools; no tokens in args/logs."""
import fcntl,hashlib,json,pathlib,re,subprocess,sys,urllib.request,uuid
H=pathlib.Path.home(); M='1ab3985a-2193-4177-8dd2-8ec7d54dbfeb';Q='51a35822-a870-43cc-a775-fd5e662f0039';key=(H/'.openhands/agent-canvas/api-key.txt').read_text().strip()
def api(p,b=None,method=None):
 r=urllib.request.Request('http://127.0.0.1:8000/api/'+p,headers={'X-Session-API-Key':key,'Content-Type':'application/json'},method=method,data=None if b is None else json.dumps(b).encode());return json.load(urllib.request.urlopen(r,timeout=30))
def git(path: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()
def main():
 mode=sys.argv[1];assert mode in ('mutation','qa');parent=M if mode=='mutation' else Q;j=api('conversations/'+parent);root=pathlib.Path(j['workspace']['working_dir']);repo=root/'repo';reg=root/'.worker-registry';reg.mkdir(exist_ok=True);assert not reg.is_symlink();lock=(reg/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX);items=[json.loads(f.read_text()) for f in sorted(reg.glob('*.json'))];statuses={x['id']:api('conversations/'+x['id'])['execution_status'] for x in items};print([(x['lane'],x['id'],statuses[x['id']]) for x in items],flush=True)
 if len(sys.argv)==2:return
 lane=sys.argv[2];assert re.fullmatch(r'[a-z0-9-]{3,70}',lane);existing=next((x for x in items if x['lane']==lane),None)
 if existing:return
 # One active lane per campaign. Prefer a queued assignment over model contention.
 assert sum(s in ('running','idle','waiting_for_confirmation') for s in statuses.values())<1,'Capacity in use: poll existing children, do not duplicate'
 task=sys.argv[3];assert 20<=len(task)<=2200
 cid=str(uuid.uuid5(uuid.NAMESPACE_URL,parent+':'+lane));d=root/'worker-trees'/lane/'monori';d.parent.mkdir(parents=True,exist_ok=True);assert not d.exists();git(repo,'fetch','https://github.com/alchemmist/monori.git','main','--depth=1');base=git(repo,'rev-parse','FETCH_HEAD');git(repo,'worktree','add','--detach',str(d),base)
 prof='socrat-'+mode+'-worker-venice';llm='v-deepseek-uc';profiles=api('agent-profiles')['profiles'];p=next((x for x in profiles if x['name']==prof),None)
 if not p:
  api('agent-profiles/'+prof,{'agent_kind':'openhands','llm_profile_ref':llm,'tools':[{'name':'terminal'},{'name':'file_editor'}],'mcp_server_refs':[],'secret_refs':[],'integration_refs':[],'public_skills':[],'system_message_suffix':'Work only in your assigned worktree. Keep output short. Do not request credentials or merge. Report evidence, PR URL or exact blocker to parent. Russian owner-facing text.','condenser':{'max_size':32,'max_tokens':10000,'keep_first':1}});p=api('agent-profiles/'+prof)['profile']
 assert p['llm_profile_ref']==llm
 rules=('Проверяй только назначенные 1–5 мутантов из #509. Сначала тесты проходили на мутанте, потом падают по нужной причине, на оригинале проходят. Меняй только малый тестовый блок. Не удаляй тесты только потому что зелёные. Дубликат или эквивалентный мутант — документируй, не публикуй фиктивный PR. Публикуй через /home/openhands/workspace/MONORI_PUBLISHER.md с текущим main SHA. Не включай мутант в PR.' if mode=='mutation' else 'Исправляй только назначенный уже опубликованный QA issue. Правила публикации в QA_PUBLICATION.md в корне QA workspace. Добавь regression и проверь локально. Собственный worktree, БД и порты. Другие агенты параллельно исследуют UI. Не трогать #509.')
 msg=f'Обязательный первый шаг: cd {d}. Все изменения, тестовые копии и артефакты только там или своём tmp. База {base}. Сверь открытые PR на дубли. Задание: {task}. {rules} Не превращай каждый мутант в отдельный PR, если один тест закрывает группу. После PR обрабатывай CI/current-head reviews/replies, без merge. Краткий журнал только в {d.parent}/PROGRESS.md. Не переустанавливай всё окружение без необходимости.'
 rec={'id':cid,'lane':lane,'base':base,'worktree':str(d),'task':task};api('conversations',{'parent_conversation_id':parent,'conversation_id':cid,'workspace':j['workspace'],'agent_profile_id':p['id'],'confirmation_policy':j['confirmation_policy'],'security_analyzer':j['security_analyzer'],'hook_config':j['hook_config'],'max_iterations':j['max_iterations'],'autotitle':False});(reg/(lane+'.json')).open('x').write(json.dumps(rec));api('conversations/'+cid,{'title':('Mutation #509' if mode=='mutation' else 'QA fix')+' — '+lane},'PATCH');print(cid,api('conversations/'+cid+'/events',{'role':'user','content':[{'type':'text','text':msg}],'run':True}),flush=True)
if __name__=='__main__':main()
