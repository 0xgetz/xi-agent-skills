---
name: server-discovery
description: Reference for all server types, connected integrations, and available servers.
---

# Server Discovery

Tool slugs use `server_id__tool_name` (double underscore). Use `tool_discovery` to get exact slugs.

The catalog below is long — a full read of this file may truncate before the entry you need.
To check whether a specific service exists, use sandbox_python to search this file for the service name.
Never conclude a service is absent from a truncated read.

## Adding a Server

Use `add_server_awaiter` with the `server_id` to add any server to this agent. Identify ALL servers a task needs upfront and add them in a single step (parallel tool calls).

## All Servers

| server_id | name | type | capability | status | authenticated | description |
|-----------|------|------|------------|--------|---------------|-------------|
| affinity | affinity | gumcp_server | manage_records | available | no | Get all opportunities in list "Prospects" |
| ahrefs | ahrefs | gumcp_server | get_data | available | no | Get backlink data for a domain and list referring domains with DR > 50 |
| airtable | airtable | gumcp_server | get_data | available | no | List all records in the "Leads" table created this month |
| apify | apify | gumcp_server | scrape_web | available | n/a | Run an Apify actor to extract product data from an e-commerce site |
| apollo | apollo | gumcp_server | enrich_data | connected | n/a | Enrich a contact by email |
| asana | asana | gumcp_server | manage_tasks | available | no | Get all tasks in a project |
| ashby | ashby | gumcp_server | recruiting | available | no | Get all candidates in the last month |
| attio | attio | gumcp_server | manage_records | available | no | Get contact details for john.doe@email.com and show recent interactions |
| beehiiv | beehiiv | gumcp_server | bulk_email | available | no | Add a subscriber to my newsletter using their email |
| box | box | gumcp_server | manage_files | available | no | List files in my root folder |
| brandfetch | brandfetch | gumcp_server | enrich_data | connected | n/a | Look up brand data, logos, and colors for gumloop.com |
| cal | cal | gumcp_server | schedule | available | no | List all events in my calendar for the next 3 days with location details |
| chorus | chorus | gumcp_server | get_data | available | no | Search meetings or calls |
| clickhouse | clickhouse | gumcp_server | get_data | available | no | Query a ClickHouse Cloud service or manage dashboards and alerts |
| confluence | confluence | gumcp_server | create_content | available | no | List all pages in a specific space |
| cursor | cursor | gumcp_server | automation | available | no | Launch a Cursor agent to implement a feature |
| databricks | databricks | gumcp_server | get_data | available | no | Query the serving endpoint |
| datadog | datadog | gumcp_server | get_data | available | no | List all monitors in critical state |
| devin | devin | gumcp_server | automation | available | no | Create a Devin session to fix a bug |
| dropbox | dropbox | gumcp_server | manage_files | available | no | List all files in a folder larger than 10MB uploaded this year |
| exa | exa | gumcp_server | search_web | available | n/a | Search the web with AI |
| excel | excel | gumcp_server | get_data | available | no | Get all rows from the "Q2 Sales" sheet where status is "Closed Won" |
| expensify | expensify | gumcp_server | payments | available | no | Get all transactions in the last month |
| extend | extend | gumcp_server | automation | available | no | Process files or documents through workflows |
| fal | fal | gumcp_server | create_content | available | n/a | Generate an image of a sunset over mountains |
| fathom | fathom | gumcp_server | get_data | available | no | Get the transcript and summary from my last meeting |
| fellow | fellow | gumcp_server | get_data | available | no | Access meeting recordings, notes, and transcripts |
| findymail | findymail | gumcp_server | enrich_data | available | no | Find verified email addresses and phone numbers for contacts |
| firecrawl | firecrawl | gumcp_server | scrape_web | available | n/a | Search, scrape, crawl, or map websites for data with Firecrawl |
| foreplay | foreplay | gumcp_server | get_data | available | n/a | Get all brands |
| freshdesk | freshdesk | gumcp_server | support | available | no | List all open tickets from the last week |
| freshsales | freshsales | gumcp_server | manage_records | available | no | List contacts and deals in Freshsales |
| gads | gads | gumcp_server | get_data | available | no | Get all campaigns for a specific account |
| gamma | gamma | gumcp_server | create_content | available | no | Create a new presentation |
| ganalytics | ganalytics | gumcp_server | get_data | available | no | Get website traffic for the last 7 days broken down by country |
| gappsheet | gappsheet | gumcp_server | get_data | available | no | Get all rows from a table where status is "Active" |
| gbigquery | gbigquery | gumcp_server | get_data | available | no | Run a SQL query on a dataset to get total sales for Q1 2024 |
| gcalendar | gcalendar | gumcp_server | schedule | available | no | Give me all meetings from the previous 24 hours with more than 2 attendees |
| gcs | gcs | gumcp_server | manage_files | available | no | Manage files and buckets |
| gdocs | gdocs | gumcp_server | create_content | available | no | Find all documents shared with me by Alice in the last month |
| gdrive | gdrive | gumcp_server | manage_files | available | no | Get all files in a folder that have "budget" in the file name |
| gdv360 | gdv360 | gumcp_server | get_data | available | no | Get all campaigns for a specific account |
| github | github | gumcp_server | manage_tasks | connected | yes | List all repositories for a user and show the number of open issues for each |
| gitlab | gitlab | gumcp_server | manage_tasks | available | no | Open a merge request from feature/x into main on mygroup/myproject |
| glooker | glooker | gumcp_server | get_data | available | no | Interact with Google Looker to run queries, manage dashboards, and schedule deliveries |
| gmail | gmail | gumcp_server | send_message | available | no | Retrieve the last 5 unread emails with attachments from my inbox |
| gmaps | gmaps | gumcp_server | get_data | available | n/a | Get directions from my current location to the office |
| gmeet | gmeet | gumcp_server | schedule | available | no | Create a new meeting for the "Engineering" team tomorrow at 10am |
| gong | gong | gumcp_server | get_data | available | no | List all calls in the last 30 days |
| gpagespeed | gpagespeed | gumcp_server | get_data | connected | n/a | Analyze the performance of a website |
| greenhouse | greenhouse | gumcp_server | recruiting | available | no | Get all candidates in the last month |
| gsearchconsole | gsearchconsole | gumcp_server | get_data | available | no | Show me top search queries for my site over the last 30 days |
| gsheets | gsheets | gumcp_server | get_data | available | no | Get all rows from the "Q2 Sales" sheet where status is "Closed Won" |
| gslides | gslides | gumcp_server | create_content | available | no | Create a presentation about Q1 results with charts and speaker notes |
| gtasks | gtasks | gumcp_server | manage_tasks | available | no | Manage tasks and task lists |
| hex | hex | gumcp_server | get_data | available | no | List all projects in my Hex workspace |
| hubspot | hubspot | gumcp_server | manage_records | available | no | Find a contact by email and show their last 3 deals |
| incident_io | incident_io | gumcp_server | support | available | no | Create a critical incident for database outage |
| instagram | instagram | gumcp_server | social_media | available | n/a | Get comments on a post |
| intercom | intercom | gumcp_server | manage_records | available | no | Get all users in the last month |
| jira | jira | gumcp_server | manage_tasks | available | no | List all issues assigned to me in the "Backend" project with priority High |
| launchdarkly | launchdarkly | gumcp_server | get_data | available | no | List all feature flags in a project |
| linear | linear | gumcp_server | manage_tasks | available | no | List all open issues assigned to me in the "Website Redesign" project |
| loops | loops | gumcp_server | bulk_email | available | no | Create a new contact |
| luma | luma | gumcp_server | schedule | available | no | List all upcoming events on my Luma calendar |
| monday | monday | gumcp_server | manage_tasks | available | no | List all items in the "Product Launch" board with status "In Progress" |
| netsuite | netsuite | gumcp_server | manage_records | available | no | Get all customers in the last month |
| notion | notion | gumcp_server | create_content | available | no | Find a page by title and list all subpages created in 2024 |
| outlook | outlook | gumcp_server | send_message | available | no | Get my last 10 unread emails |
| outlook_calendar | outlook_calendar | gumcp_server | schedule | available | no | Get all my meetings for today |
| pagerduty | pagerduty | gumcp_server | support | available | no | Get all alerts in the last 24 hours |
| parallel | parallel | gumcp_server | search_web | available | n/a | Search the web with AI |
| pipedrive | pipedrive | gumcp_server | manage_records | available | no | Get all deals in the last month |
| postgresql | postgresql | gumcp_server | get_data | available | no | Get all tables in a database |
| quickbooks | quickbooks | gumcp_server | payments | available | no | Analyze cash flow trends and generate financial metrics for my business |
| reddit | reddit | gumcp_server | social_media | available | no | Get the latest posts from the r/machinelearning subreddit with more than 100 upvotes |
| reducto | reducto | gumcp_server | other | connected | n/a | Summarize a document and highlight the top 3 key points |
| salesforce | salesforce | gumcp_server | manage_records | available | no | Get Account details by account id and list all open opportunities |
| salesloft | salesloft | gumcp_server | manage_records | available | no | Get all contacts in the last month |
| seismic | seismic | gumcp_server | get_data | available | no | Perform operations on Seismic content, users, and engagements |
| semrush | semrush | gumcp_server | get_data | available | n/a | Get all keywords for a specific domain |
| shopify | shopify | gumcp_server | payments | available | no | List all products in the store that are out of stock |
| sigma_computing | sigma_computing | gumcp_server | get_data | available | no | Interact with Sigma Computing to manage workbooks, data, and analytics |
| slack | slack | gumcp_server | send_message | available | no | Get all messages from the #general channel from Ben in the last 3 days |
| snowflake | snowflake | gumcp_server | get_data | available | no | Get all tables in a database |
| sprig | sprig | gumcp_server | get_data | available | no | Retrieve survey responses and analyze user feedback |
| stripe | stripe | gumcp_server | payments | available | no | Get all invoices for a specific customer |
| tableau | tableau | gumcp_server | get_data | available | no | Interact with Tableau to access dashboards, data, and metrics |
| teams | teams | gumcp_server | send_message | available | no | Get all members in a team |
| tiktok | tiktok | gumcp_server | social_media | available | n/a | Get comments on a post |
| trello | trello | gumcp_server | manage_tasks | available | no | List all cards on my "Product Roadmap" board |
| webflow | webflow | gumcp_server | create_content | available | no | List all sites and collections |
| word | word | gumcp_server | create_content | available | no | Create a document with the title "AI Trends 2050" |
| workday | workday | gumcp_server | recruiting | available | no | Download report from url |
| x | x | gumcp_server | social_media | available | no | Search for tweets about AI and get the top 10 results |
| youtube | youtube | gumcp_server | social_media | available | n/a | Get all videos from a channel |
| zendesk | zendesk | gumcp_server | support | available | no | List all open tickets assigned to the "Support" group in the last 48 hours |
| zoom | zoom | gumcp_server | schedule | available | no | Get all meetings in the last month |

**Status**: `connected` = ready to use, `available` = can be added, `blocked` = restricted by org policy.
