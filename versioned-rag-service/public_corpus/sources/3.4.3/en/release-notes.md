## DSIP

<details><summary>Click to expand</summary>

- [DSIP-107][Scheduler] Add schedule missed fire policy (#18464) @liang-wenjie

</details>

## Improvement

<details><summary>Click to expand</summary>

- [Improvement-18040] [Doc] Update the parameter priority explanation in the docs. (#18321) @njnu-seafish
- [Doc-18322][Parameter] Add a note to the parameter priority documentation specifying and fix some issues (#18323) @njnu-seafish
- [Improvement-18304][API] Remove dead code after t_ds_relation_user_alertgroup… (#18316) @det101
- [Improvement-18332][Worker] Remove plaintext passwords from the logs (#18333) @njnu-seafish
- [Improvement-17563][Helm] Update mysql helm chart version (#18336) @qiuyanjun888
- [Doc-18326][Parameter] Fix and Enrich the documentation for parameter priority. (#18327) @njnu-seafish
- [Improvement-18354][UI] Change the description field to optional (#18355) @njnu-seafish
- [Improvement-18359][UI] Change the description field to optional in k8s config (#18360) @njnu-seafish
- [Improvement-17933][api] Restrict audit logs to current user for non-admin users (#18368) @qiuyanjun888
- [Improvement-18403][API&Security] Avoid raw password exposure in user parameter validation errors (#18404) @njnu-seafish
- [Improvement-18412][api] Fix missing validation for resource preview limit parameter (#18411) @destinyoooo
- [Improvement-18388][TASK]Killed shell tasks should be displayed as FAILURE (#18407) @HomminLee
- [Improvement-18437][API] Add index idx_project_submit_time for queryTaskInstanceListPaging (#18438) @njnu-seafish
- [Improvement-18439][API]Add composite index idx_project_start_time for workflow instance query (#18440) @njnu-seafish
- [Improvement-18441][API&DAO] Optimize TaskInstanceMapper to exclude large text fields from list queries (#18442) @njnu-seafish
- [Doc-18474][Upgrade] Fix zh/en incompatible upgrade docs out of sync (#18478) @njnu-seafish
- [Improvement-18556][API] Remove obsolete dynamic sub-workflow API (#18557) @ruanwenjun
- [Improvement-18558][API] Harden user list access and responses (#18560) @ruanwenjun
- [Improvement-18563][API] Refine datasource authorization list APIs (#18564) @ruanwenjun
- [Improvement-18568][API] Remove obsolete task update-with-upstream API (#18569) @ruanwenjun
- [Improvement-18580][api] Fix typo in DataSourceServiceImpl log message (#18581) @kittimzhe
- [Improvement-18443][API&DAO] Optimize WorkflowInstanceMapper to exclude large text fields from list queries (#18444) @njnu-seafish
- [Improvement-18589][API] Align cluster query permissions (#18590) @ruanwenjun
- [Chore] Remove unused code (#18599) @SbloodyS

</details>

## Bugfix

<details><summary>Click to expand</summary>

- [Fix-18330] Replace HashMap with ConcurrentHashMap in UserGroupInformationFactory to avoid ConcurrentModificationException (#18331) @eye-gu
- [Fix-18340][Helm] Fix duplicate app.kubernetes.io/name label on ConfigMap (#18341) @vlaborie
- [Fix-18346] countTaskInstanceStateByProjectCodes uses submit_time filtering (#18347) @eye-gu
- [Improvement-17705] Add kill-application-when-task-failover logic (#18353) @SbloodyS
- [Fix-17794] Fix rerun workflow instance should follow the specified workerGroup parameter (#18352) @SbloodyS
- [Fix-18247] Fix when forceTaskSuccess is performed on the last unsuccessful workflow instance, the workflow instance cannot be reset to the success state (#18351) @SbloodyS
- [Fix-18307][API] The frontend is correctly using the preferred values of the associated project for task creating and workflow scheduling (#18308) @njnu-seafish
- [Fix-18378] Fix list resources returned only 1000 records in s3 storage type (#18381) @SbloodyS
- [Fix-18391] [Alert] Remove redundant plugin definition table existence check during AlertServer startup (#18392) @njnu-seafish
- [Fix-18409][Common] Fix DAG.addEdge accepting an edge that creates a cycle when paths converge (#18410) @nkuprins
- [Fix-18406] Fix task instance failed but workflow instance remains in running state while using continue strategy with a blocked intermediate predecessor (#18415) @SbloodyS
- [Fix-18338] Check task if it's waiting for TaskGroup slot when pause/kill (#18414) @SbloodyS
- [Fix-18446][task-sql]Persist sqlSource and sqlResource fields when saving SQL task node (#18447) @nanxiuzi
- [Fix-18540][Master] Reset the runtime state when recreating a failed task instance (#18541) @SEPURI-SAI-KRISHNA
- [Fix-18538][Master] Schedule task retry at endTime + retryInterval (#18539) @SEPURI-SAI-KRISHNA
- [Fix-18562][Common] FileUtils.writeContent2File fails for parentless paths (#18408) @hiSandog
- [Fix-18559][API] Align workflow mutations with project write permissions (#18561) @ruanwenjun
- [Fix-18570][Master] Detect wrapped CommandDuplicateHandleException in bootstrapError (#18570) (#18573) @hellodml
- [Fix-18565][API] Validate datasource access for task definitions (#18566) @ruanwenjun
- [Doc-18579] Fix malformed links in datasource and configuration docs (#18578) @kittimzhe
- [Fix-18582][API] Align actuator endpoint matching (#18583) @ruanwenjun
- [Fix-18596][API] Enforce permission checks for sub-workflow references (#18597) @ruanwenjun
- [Fix-17883] Fix K8s Alert HTTP test sending failed by using IP for non-StatefulSet pods (#18574) @zhang-arvin
- [Fix-18389][DataX] Read job definition from attached resource file when custom json is empty (#18434) @nikhiln64
- [Fix-18576][Dependent Task] Fix parsing for ALL dependent tasks (#18605) @yan9651688
- [Fix-18601][Alert] Align Alert Script test-send behavior (#18602) @ruanwenjun
- [Fix-18604][Master] Preserve forced-success state when recovering failed workflows (#18608) @wcmolin

</details>

## Document

<details><summary>Click to expand</summary>

- [Chore][API] Remove obsolete cluster query-by-code API (#18584) @ruanwenjun
- [Chore] Update next release version to 3.4.3 (#18613) @ruanwenjun

</details>

## Chore

<details><summary>Click to expand</summary>

- [Chore] Fix sonar token leak (#18363) @SbloodyS
- [Chore] Remove sonar check (#18374) @SbloodyS
- [Chore] Fix auto labeler error (#18375) @SbloodyS

</details>