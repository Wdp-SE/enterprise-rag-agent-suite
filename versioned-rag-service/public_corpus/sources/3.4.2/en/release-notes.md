## DSIP

<details><summary>Click to expand</summary>

- [DSIP-37] Disable HTTP TRACE requests in jetty via configuration (#18119) @SbloodyS
- [DSIP-95][API] Complete the functionality of using dependencies in the complement data (#18003) @det101

</details>

## Feature

<details><summary>Click to expand</summary>

- [Feature-18070][Task] Add Amazon EMR Serverless task plugin (#18069) @norrishuang
- [Feature-18136][API] Support view the running task/workflow of a active master/worker at UI monitor page (#18138) @ruanwenjun

</details>

## Improvement

<details><summary>Click to expand</summary>

- [Improvement-17986][task-plugin] Support parameter replacement in Flink and FlinkStream task (#17987) @macdoor
- [Chore][Doc] Fix typos in WorkflowInstanceServiceTest and JVM.json (#18018) @sanjana2505006
- [Improvement-17947][ui] Improve delete confirmation to show workflow name (#18029) @asadjan4611
- [Improvement-17874][ApiServer] Remove the default value of expireTime and let the user choose the time (#17907) @njnu-seafish
- [Improvement-17942][API&UI]Add startParams validation logic in both the frontend and backend. (#17956) @njnu-seafish
- [Improvement-18056][ui] Remove the unused code in dolphinscheduler-ui (#18057) @ruanwenjun
- [Improvement-18056][api] Remove the unused code in dolphinscheduler-api (#18058) @ruanwenjun
- [Improvement-18056][Alert] Remove the unused code in alert module (#18062) @ruanwenjun
- [Improvement-18045][Doc]Improvement Parameter passing behavior doc (#18046) @njnu-seafish
- [Improvement-17010][datax] Add datax channel count to a custom parameter. (#17898) @HEEKDragonOne
- [Improvement-17960][API]Add null/empty/duplicate validation logic for globalParams when creating or updating a workflow (#17961) @njnu-seafish
- [Chore] Update download URL for DolphinScheduler tarball (#18087) @pjfanning
- [Doc-18078] document improvement (#18079) @SbloodyS
- [Improvement-17908][Flink] Make -sae parameter configurable in UI with default off (#17909) @leocook
- [Chore] Remove LICENSE files of dependencies under Apache License 2.0 (#17768) @ruanwenjun
- [Improvement-18051][alert] Remove unused dead code in WeChatSender mkString (#18100) @asadjan4611
- [Improvement-18095][API-Test] Add dependent task api test case (#18096) @SbloodyS
- [Improvement-18072][Api] Add user permission validation logic to the connectionTest, getDatabases, getTables, and getTableColumns methods in DataSourceController (#18073) @njnu-seafish
- [Improvement-18056] Remove unused code in dao module (#18107) @SbloodyS
- [Improvement-18056] Remove unused code in api module (#18105) @SbloodyS
- [Improvement-18056] Remove unused code in common module (#18104) @SbloodyS
- [Improvement-18056] Remove unused code in alert module (#18103) @SbloodyS
- [Improvement-18056] Remove unused code in datasource module (#18111) @SbloodyS
- [Improvement-18056] Remove unused code in service module (#18112) @SbloodyS
- [Improvement-18056] Remove unused code in spi module (#18113) @SbloodyS
- [Improvement-18056] Remove unused code in storage module (#18114) @SbloodyS
- [Improvement-18056] Remove unused code in task plugin module (#18115) @SbloodyS
- [Improvement-18056] Remove unused code in tools module (#18116) @SbloodyS
- [Improvement-18056] Remove unused code in yarn aop module (#18117) @SbloodyS
- [Improvement-18056] Remove unused code in worker module (#18118) @SbloodyS
- [Doc-18120] Remove irrelevant windows system documents (#18121) @SbloodyS
- [Improvement-17433] Support identify IPv6 addresses properly (#18126) @SbloodyS
- [Improvement-18084][API] Address the inconsistent class comments in DataSourceService and DataSourceServiceImpl classes. (#18086) @njnu-seafish
- [Improvement-18127][Master] Remove the redundant workflow completion check when handling workflow timeout events (#18128) @njnu-seafish
- [Improvement-17564][Helm] Update minio helm chart version (#18122) @SbloodyS
- [Improvement-17562][Helm] Update postgresql helm chart version (#18123) @SbloodyS
- [Improvement-17561][Helm] Update zookeeper helm chart version (#18124) @SbloodyS
- [Improvement-18056] Clean up unused methods and classes in the dolphinschudler-api module (#18134) @njnu-seafish
- [Chore] Bump lodash (#18141) @SbloodyS
- [Chore] Bump up vite (#18144) @SbloodyS
- [Improvement-18142][Datasource] Normalize the use of the DataSourceConstants class (#18143) @njnu-seafish
- [Improvement-18019][task-sql] Support SQL from resource file and parameter placeholders (#18020) @macdoor
- [Improvement-18056] Clean up unused methods and classes in the dolphinschudler-common module (#18147) @njnu-seafish
- [Improvement-18151] Simplify the code with lombok annotations (#18152) @SbloodyS
- [Improvement-18056] Clean up unused methods and classes in the dolphinschudler-dao-plugin module (#18156) @njnu-seafish
- [Chore] Remove unused method in IWorkflowFailureStrategy (#18159) @ruanwenjun
- [Improvement-18137][Master] Rename IWorkflowExecutionRunnable/ITaskExecutionRunnable to IWorkflowExecution/ITaskExecution (#18163) @ruanwenjun
- [Improvement-18056] Clean up unused methods and classes in the dolphinschudler-dao module (#18153) @njnu-seafish
- [Improvement-18161][Pom] Does not support automatic hot-reloading of configuration files from ConfigMap (#18162) @ruanwenjun
- [Chore] Fix code scaning and cve (#18167) @SbloodyS
- [Improvement-18056] Clean up unused methods and classes in the dolphinschudler-service module (#18169) @njnu-seafish
- [Improvement-18056] Clean up unused methods and classes in the dolphinschudler-registry module (#18165) @njnu-seafish
- [Improvement-17843][Master] Add IT case for task timeout alert (#18001) @shrihari7396
- [Improvement-18064][ApiServer] Update globalParams replace logic and test case (#18068) @njnu-seafish
- [Improvement-18056] Clean up unused methods and classes in the dolphinschudler-master module (#18164) @njnu-seafish
- [Doc-18193][dolphinscheduler-alert-http] Fix incorrect alert param doc (#18194) @SbloodyS
- [Improvement-16754][DataX] Support DataX writer parameter batchSize (#18192) @leocook
- [Chore] Unit-Test optimize (#18214) @SbloodyS
- [Improvement-18224][API] Migrate K8sNamespaceService Map<String,Object> returns to typed returns (#18227) @ruanwenjun
- [Doc-18239] Fix outdated Spark documentation links (#18241) @llphxd
- [Improvement-18224][API] Migrate SchedulerService Map<String,Object> returns to typed returns (#18226) @ruanwenjun
- [Improvement-18224][API] Migrate WorkerGroupService Map<String,Object> returns to typed returns (#18228) @ruanwenjun
- [Improvement-18224][API] Migrate TaskDefinitionService Map<String,Object> returns to typed returns (#18229) @ruanwenjun
- [Improvement-18224][API] Migrate WorkflowInstanceService Map<String,Object> returns to typed returns (#18232) @ruanwenjun
- [Fix-18222][JdbcRegistry] Reuse a singleton scheduler executor in JdbcRegistryThreadFactory (#18223) @ruanwenjun
- [Improvement-18224][API] Migrate small-service Map<String,Object> returns to typed returns (#18230) @ruanwenjun
- [Improvement-18224][API] Migrate UsersService Map<String,Object> returns to typed returns (#18234) @ruanwenjun
- [Improvement-18224][API] Migrate WorkflowDefinitionService Map<String,Object> returns to typed returns (#18236) @ruanwenjun
- [Improvement-18224][API] Migrate TaskGroupService and ExecutorServiceforceStartTaskInstance to typed returns (#18233) @ruanwenjun
- [Improvement-18224][API] Migrate ProjectService Map<String,Object> returns to typed returns (#18245) @ruanwenjun
- [Improvement-18249][DAO] Route ProjectMapper and WorkflowDefinitionMapper access through repository Dao (#18250) @ruanwenjun
- [Improvement-18249][DAO] Route ScheduleMapper access through ScheduleDao (#18251) @ruanwenjun
- [Improvement-18249][DAO] Route TaskInstanceMapper access through TaskInstanceDao (#18252) @ruanwenjun
- [Improvement-18249][DAO] Route ClusterMapper and K8sNamespaceMapper access through repository Dao (#18257) @ruanwenjun
- [Improvement-18249][DAO] Route TenantMapper access through TenantDao (#18258) @ruanwenjun
- [Improvement-18249][DAO] Route UserMapper access through UserDao (#18253) @ruanwenjun
- [Improvement-18249][DAO] Route WorkflowTaskRelationMapper access through WorkflowTaskRelationDao (#18260) @ruanwenjun
- [Improvement-18249][DAO] Route DataSourceMapper and DataSourceUserMapper access through repository Dao (#18259) @ruanwenjun
- [Improvement-18249][DAO] Route WorkflowInstanceMapper access through WorkflowInstanceDao (#18256) @ruanwenjun
- [Improvement-18249][DAO] Route QueueMapper access through QueueDao (#18263) @ruanwenjun
- [Improvement-18249][DAO] Route ProjectUserMapper access through ProjectUserDao (#18262) @ruanwenjun
- [Improvement-18249][DAO] Route AlertGroupMapper and AccessTokenMapperaccess through repository Dao (#18261) @ruanwenjun
- [Improvement-18249][DAO] Route TaskDefinitionMapper access through TaskDefinitionDao (#18254) @ruanwenjun
- [Improvement-18267][Remote Logging] Allow custom S3 region with endpoint (#18268) @wcmolin

</details>

## Bugfix

<details><summary>Click to expand</summary>

- [Fix-17464] Use Driver to create jdbc connection (#18033) @ruanwenjun
- [Fix-18054] [DependentTask] Cannot dependent single task due to dao error (#18055) @ruanwenjun
- [Fix-18053] Fix publish-docker error (#18059) @SbloodyS
- [Fix-18041][Worker]Fix Parameter passing feature is unavailable in K8S Task (#18042) @njnu-seafish
- [Fix-18043][Worker]Fix Parameter passing feature is unavailable in Zeppelin Task (#18044) @njnu-seafish
- [Fix-17773][ApiServer] Replace the TaskCode references within the task parameters for ConditionTask and SwitchTask when coping workflow (#17982) @njnu-seafish
- [Fix-18061] Fix end time is empty when workflow insstance stopped by serial discard (#18076) @SbloodyS
- [Fix-17906] Fix can't get pod's log in k8s task (#18075) @SbloodyS
- [Fix-17389][Http-Task] Fix json parsing exception in request body (#18085) @SbloodyS
- [Fix-17847] Fix incWorkflowInstanceByStateAndWorkflowDefinitionCode not called in version 3.4.0 (#18082) @SbloodyS
- [Fix-17767][Master] fix execute task in workflow instance not effective (#18000) @Mrhs121
- [Fix-17943][dolphinscheduler-task-dinky] When DolphinScheduler calls a Dinky job and passes date parameters, the actual values are not being replaced (#18080) @shaolei7788
- [Fix-17817][Master] Add workflow timeout event and handle (#18063) @njnu-seafish
- [Fix-18132][API] Sync workflow definition version back after create/update (#18133) @wcmolin
- [Fix-18139][Docker] Docker compose deployment error (#18140) @SbloodyS
- [Fix-17557] Fix helm chart deploy error (#18148) @SbloodyS
- [Fix-18154] Fix abnormal transmission of sub-workflow complement date (#18155) @SbloodyS
- [Fix-18131] Workflow instance stuck in RUNNING state forever when using CONTINUE failure strategy with a failed upstream task (#18146) @SbloodyS
- [Fix-18168] Fix OBS listStorageEntity not returning subdirectories (#18170) @CloudExtreme
- [Fix-18182][API] User can delete task definitions in unauthorized projects (#18183) @ruanwenjun
- [Chore][UI] Fix @types/lodash version causing pnpm install failure (#18187) @Mrhs121
- [Fix-18199][Doc] Fix incorrect description of Serial Discard execution strategy (#18204) @ruanwenjun
- [Fix-18197][Master] Fix master failover releasing wrong lock path (#18207) @ruanwenjun
- [Fix-18177][Task Plugin] Fix AliyunServerlessSpark plugin dependency conflicts and improve exception handling (#18180) @includetts
- [Fix-18211][API] Add missing project authorization on view-gantt/view-variables and trigger workflow APIs (#18212) @ruanwenjun
- [Fix-18201][TaskPlugin] Fix RemoteShell task NullPointerException and… (#18210) @leocook
- [Fix-18269][Master] Move LogicFakeTask to test scope (#18270) @ruanwenjun
- [Fix-18276][API] Fix alert plugin instance permission check (#18279) @ruanwenjun
- [Fix-18283][API] Add project permission check on workflow lineage and workflow-definition list endpoints (#18284) @ruanwenjun
- [Fix-18292][Registry] Carry deleted node value in JDBC registry REMOVE event (#18296) @ruanwenjun
- [Fix-18299][API] Enforce access token owner checks (#18300) @ruanwenjun
- [Fix-18302][Common] Fix SQL license header parsing (#18301) @hiSandog

</details>

## Document

<details><summary>Click to expand</summary>

- [Chore] Initialize CLAUDE.md (#18188) @ruanwenjun
- [Improvement-18224][API] Migrate EnvironmentService Map<String,Object> returns to typed returns (#18225) @ruanwenjun
- [Chore][Master] Quietly exit WorkerGroupDispatcher loop on interrupt (#18240) @ruanwenjun
- [Chore][Docs] Refresh commit message convention to match current practice (#18242) @ruanwenjun
- [Chore][Docs] Add AGENT.md (#18271) @ruanwenjun
- [Chore][Doc] Fix English FAQ answer formatting (#18288) @hiSandog

</details>

## Chore

<details><summary>Click to expand</summary>

- [Chore][Doc] Fix typo proejct in WorkflowInstanceServiceTest (#18037) @sanjana2505006
- [Chore] Polish CI (#18088) @SbloodyS
- [Chore] Polish CI (#18090) @SbloodyS
- [Chore] Polish ci (#18093) @SbloodyS
- [Chore] Polish ci (#18102) @SbloodyS
- [Chore] Change code owner (#18145) @SbloodyS
- [Chore] Fix publish docker error (#18149) @SbloodyS
- [Chore] Remove .flake8 file (#18160) @ruanwenjun
- [Chore][CI] Temporarily disable PythonTaskE2ETest due to CI runner issue (#18208) @ruanwenjun
- [Chore] Reverts #18153 (#18206) @ruanwenjun
- [Chore] Fix UT will be skip at CI (#18205) @ruanwenjun
- [Chore] Unit-Test performance optimize (#18213) @SbloodyS
- [Chore] Recover python e2e test in ci (#18209) @SbloodyS
- [Chore] Hotfix ut ci (#18221) @SbloodyS
- [Chore][API] Remove deprecated ProjectService#checkProjectAndAuth (#18218) @ruanwenjun

</details>