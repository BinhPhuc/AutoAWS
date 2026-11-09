// All user-facing UI strings (English). Agent answers come from the backend (Vietnamese) and are shown as-is.

export const S = {
  app: {
    name: 'AutoAWS',
    tagline: 'AI troubleshooting assistant for AWS',
  },
  nav: {
    connect: 'Connections',
    chat: 'Diagnose',
    checklist: 'Checklist',
    openMenu: 'Open menu',
    toggleTheme: 'Toggle theme',
  },
  common: {
    loading: 'Loading…',
    retry: 'Retry',
    cancel: 'Cancel',
    delete: 'Delete',
    copy: 'Copy',
    copied: 'Copied',
    copyFailed: 'Could not copy. Select and copy the code manually.',
    close: 'Close',
    somethingWentWrong: 'Something went wrong',
    networkError: 'Cannot reach AutoAWS. Check your connection and try again.',
  },
  status: {
    connected: 'Connected',
    pending: 'Not verified',
    failed: 'Failed',
  },
  connections: {
    title: 'AWS connections',
    subtitle: 'Connect an AWS account with read-only access to start diagnosing.',
    add: 'Add connection',
    empty: 'No connections yet',
    emptyHint: 'Add an AWS account to start. AutoAWS only needs read-only permissions.',
    verify: 'Verify',
    verifying: 'Verifying…',
    startChat: 'Diagnose',
    region: 'Region',
    regionNames: {
      'ap-southeast-1': 'Singapore',
      'ap-southeast-2': 'Sydney',
      'ap-northeast-1': 'Tokyo',
      'ap-northeast-2': 'Seoul',
      'ap-south-1': 'Mumbai',
      'us-east-1': 'N. Virginia',
      'us-east-2': 'Ohio',
      'us-west-1': 'N. California',
      'us-west-2': 'Oregon',
      'eu-west-1': 'Ireland',
      'eu-west-2': 'London',
      'eu-central-1': 'Frankfurt',
    },
    account: 'Account',
    lastVerified: 'Last verified',
    never: 'never',
    deleteConfirmTitle: 'Delete connection?',
    deleteConfirmBody: 'Conversations linked to this connection will also be removed.',
    typeAccessKey: 'Access key',
    typeRole: 'IAM role',
    form: {
      roleOnlyHint:
        'Connect with an IAM role. Choose how you want to create the read-only role in your AWS account.',
      title: 'Add AWS connection',
      description:
        'AutoAWS only reads configuration, logs and metrics. It never modifies resources.',
      name: 'Name',
      namePlaceholder: 'e.g. Lab account',
      region: 'Region',
      roleArn: 'Role ARN',
      roleHelpButton: 'Don’t know how to get a Role ARN? Click here',
      roleHelpDescription:
        'Choose how to create a read-only role in your AWS account. When it is ready, paste its ARN into the connection form.',
      manualSetup: 'Manual setup (IAM)',
      automaticSetup: 'Automatic setup (CloudFormation)',
      manualTitle: 'Create the role in IAM',
      manualHint:
        'Create AutoAWSReadOnly in IAM, paste the trust and read-only policies from the guide, then copy the role ARN into the form below.',
      manualHelpDescription:
        'Create the role and add its policies in IAM. The guide includes everything you need to copy into AWS.',
      roleArnReadyHint: 'Already have this role? Paste its ARN in the form below.',
      automaticHint:
        'Upload a prepared template to CloudFormation. AWS creates the role and its read-only policy for you.',
      roleArnPlaceholder: 'arn:aws:iam::123456789012:role/AutoAWSReadOnly',
      externalId: 'External ID',
      externalIdHint:
        'Use this exact value in the role trust policy. Changing it requires updating the policy in AWS.',
      regenerate: 'Regenerate',
      submit: 'Save & verify',
      submitRole: 'Save & verify',
      roleReady:
        'Your connection has been saved. Verify it to confirm AutoAWS can access your resources.',
      submitting: 'Saving…',
      errors: {
        nameRequired: 'Name is required',
        regionRequired: 'Region is required',
        roleArnInvalid: 'Role ARN must look like arn:aws:iam::<account>:role/<name>',
      },
    },
    guide: {
      roleTitle: 'How to get your Role ARN',
      roleIntro:
        'An IAM role lets you grant AutoAWS read-only access to your AWS resources. Follow the steps below in your AWS account. You can complete this setup without sharing access keys.',
      roleNameLabel: 'Role name',
      requiredExact: 'Required · exact name',
      suggested: 'Suggested name',
      policyNameLabel: 'Inline policy name',
      policyName: 'AutoAWSReadOnlyDiagnostics',
      policyNameHint:
        'This name labels the policy inside your role. You can use this suggestion or choose another name.',
      finalReviewTitle: 'Before you choose Create role',
      finalReviewItems: [
        '**Step 1: Select trusted entities** — confirm the trusted account and **External ID** match the trust policy you copied earlier. Use **Edit** if you need to correct it.',
        '**Step 2: Add permissions** — review the **Inline policy summary**, including the **Allow** and **Explicit deny** sections. Use **Edit** if the permissions do not match the policy you pasted.',
        '**Step 3: Add tags** — tags are **optional**. Leave them empty unless your organization requires them.',
      ],
      keepUnchanged: 'Keep unchanged',
      externalIdNote:
        'This value is unique to this connection and is already included in the trust policy. Keep it unchanged when you return to the connection form.',
      roleName: 'AutoAWSReadOnly',
      roleNameHint:
        'Copy this exact name, including capitalization. Keep the role path set to the default (/).',
      connectionExternalId: 'External ID for this connection',
      setupUnavailable:
        'We couldn’t prepare your connection policy. Please try again later or contact support.',
      roleSteps: [
        {
          id: 'console',
          title: 'Open IAM in your AWS account',
          body: 'Sign in to the AWS Management Console in a new tab. Make sure you are in the account you want to connect. Search for **IAM**, open it, then select **Roles → Create role**. If you cannot create a role, ask your AWS administrator to help with these steps.',
        },
        {
          id: 'trust',
          title: 'Select trusted entity',
          body: 'Select **Custom trust policy**. Copy the policy below and **replace the entire contents** of the AWS editor with it, then choose **Next**. This policy identifies AutoAWS as the trusted service and includes the External ID for your connection. No changes to the policy are needed.',
        },
        {
          id: 'read',
          title: 'Add permissions',
          body: 'On **Add permissions**, select **Create inline policy**. Under **Policy**, click inside the JSON editor, **select all existing text**, and replace it with the complete read-only policy below.',
          after:
            'Check the **Errors** tab below the editor and fix any JSON errors. When the policy is valid, choose **Next** to continue to **Name, review, and create**. The inline policy will be saved with your role when you finish creating it.',
        },
        {
          id: 'name',
          title: 'Name, review, and create',
          body: 'Under **Role details**, enter the exact **Role name** shown below. You can leave **Description** empty. Further down, under **Step 2: Add permissions → Inline policy summary**, enter the **Inline policy name** shown below.',
          after:
            'After checking the sections above, choose **Create role** at the bottom of the page. AWS saves the role and its inline policy together.',
        },
        {
          id: 'arn',
          title: 'Copy the Role ARN',
          body: 'Return to **IAM → Roles → AutoAWSReadOnly**. In **Summary**, find **ARN** and use its copy button. Copy the **complete ARN**, for example `arn:aws:iam::123456789012:role/AutoAWSReadOnly`. Yours will contain your own account ID.',
        },
        {
          id: 'connect',
          title: 'Finish the connection in AutoAWS',
          body: 'Close this help popup and paste the ARN into **Role ARN**. Enter a connection **Name** and select the **Region** containing your resources. **Keep the External ID unchanged.** Choose **Save & verify**. A successful check shows **Connected**.',
        },
      ],
      existingRoleHint:
        'Already have an AutoAWSReadOnly role? Check Trust relationships against step 2 and Permissions against step 3, then copy its ARN in step 5. If the role is already used for another connection, ask your AWS administrator before changing it.',
      trustTitle: 'Trust policy JSON',
      trustHint:
        'Ready to copy. The AutoAWS account and your connection’s External ID are already filled in.',
      readTitle: 'Read-only permissions policy',
      readHint:
        'This policy lets AutoAWS inspect the resource configuration needed to diagnose issues. It also blocks access to S3 object contents, stored secrets, and the other data listed in its Deny statement.',
      cliTitle: 'Optional: look up the ARN with AWS CLI',
      cliHint:
        'If you already use AWS CLI, you can run this command while signed in to your AWS account with iam:GetRole permission. You can also copy the ARN from the console in step 5.',
      readError: 'We couldn’t load the permissions policy. Please try again later.',
      noTools:
        'Connection setup is temporarily unavailable. Please try again later or contact support.',
      docsRole: 'AWS guide: role trust policies',
      revokeAccessNote: 'You can remove AutoAWS access at any time by deleting this role in IAM.',
    },
    cfn: {
      title: 'Create your role with CloudFormation',
      intro:
        'This template creates AutoAWSReadOnly with a trust policy and read-only permissions. Its AutoAWS account ID and your connection’s External ID are already filled in.',
      existingRole:
        'Already created AutoAWSReadOnly? Use the Manual setup (IAM) tab to check it and copy its ARN. Choose one setup method; deploying this template when the role already exists will fail.',
      step1:
        'Download **autoaws-role.yaml** below, or copy the template into a file with that name.',
      step2:
        'Sign in to your AWS account. Open **CloudFormation → Stacks → Create stack → With new resources (standard)**. Choose **Choose an existing template → Upload a template file**, select **autoaws-role.yaml**, then choose **Next**.',
      step3:
        'Enter the **Stack name** shown above. **Keep PlatformAccountId and ExternalId unchanged**, then choose **Next**.',
      step4:
        'Review the stack options. **Acknowledge that CloudFormation may create IAM resources with custom names** wherever AWS requests it, then continue to the review page. Check the template and parameters, and choose **Submit** or **Create stack**.',
      step5:
        'Wait until the stack shows **CREATE_COMPLETE**. Open **Outputs** and copy the **Value** for **RoleArn**.',
      step6:
        'Close this popup and paste **RoleArn** into the **Role ARN** field. Choose the **Region** containing your resources, **keep this External ID unchanged**, and choose **Save & verify**.',
      copyTemplate: 'Copy template',
      downloadTemplate: 'Download template',
      templateFileName: 'autoaws-role.yaml',
      showTemplate: 'View template',
      externalId: 'External ID',
      stackName: 'Stack name',
      loadError: 'We couldn’t prepare the template. Please try again.',
      docs: 'AWS guide: create a CloudFormation stack',
    },
  },
  chat: {
    title: 'Diagnose',
    connection: 'Connection',
    selectConnection: 'Select a connection',
    noConnectedConnection: 'No verified connection. Verify one first.',
    goToConnections: 'Go to connections',
    newConversation: 'New conversation',
    conversations: 'Conversations',
    noConversations: 'No conversations yet',
    untitled: 'New conversation',
    composerPlaceholder: 'Describe the problem… (Enter to send, Shift+Enter for newline)',
    send: 'Send',
    stop: 'Stop',
    emptyTitle: 'What is going wrong?',
    emptyBody:
      'Describe the incident in your own words. AutoAWS will read the relevant configuration, logs and change history from your account and explain the root cause with evidence.',
    examples: [
      'Tôi không SSH được vào instance web-server, Security Group đã mở port 22 rồi.',
      'Tôi chạy ứng dụng Docker ở port 8080, đã trỏ app.example.com về EC2 nhưng không vào được.',
      'Từ chiều nay website báo lỗi 502 Bad Gateway, trước đó vẫn chạy bình thường.',
    ],
    thinking: 'Thinking…',
    streamError: 'The diagnosis was interrupted',
    deleteConversation: 'Delete conversation',
  },
  timeline: {
    summary: (n: number, ms: number) =>
      `Read ${n} data source${n === 1 ? '' : 's'} · ${(ms / 1000).toFixed(1)}s`,
    running: 'Running…',
    input: 'Input',
    output: 'Output',
    error: 'Error',
  },
  diagnosis: {
    rootCause: 'Root cause',
    evidence: 'Evidence',
    howToFix: 'How to fix',
    notVerified: 'Not verified',
    verifiedBadge: 'Verified from AWS',
    checkManually: 'Check manually',
    confidence: {
      high: 'High confidence',
      medium: 'Medium confidence',
      low: 'Low confidence',
    } as Record<string, string>,
  },
  checklist: {
    title: 'Checklist',
    comingSoon: 'Coming soon',
    body: 'Run a checklist against your environment (e.g. "No security group opens port 22 to 0.0.0.0/0"). Each item is evaluated as Pass / Fail / Not enough data, with evidence.',
  },
} as const
