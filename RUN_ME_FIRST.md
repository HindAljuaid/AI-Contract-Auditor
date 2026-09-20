# Run Me First

## Start the app on macOS

Open Terminal and run:

```bash
cd ~/Downloads/insurance_auditor_app
chmod +x run_app.sh
./run_app.sh
```

The first run creates `.venv`, installs the pinned packages, and starts Streamlit.

## First test — Hospital 1 Validation

1. In the sidebar select **Provided hospital data**.
2. Select **Hospital 1**.
3. Open **H1 Validation**.
4. Click **Run validation**.

Expected result:

```text
Perfect categories: 18/18
Mean precision: 1.000
Mean recall: 1.000
```

No OpenAI API key is required. The raw execution log is optional and hidden by default.

## Run a normal audit

1. Select a hospital under **Provided hospital data**, or choose **Upload my own files**.
2. Keep **Use AI to read contract** enabled.
3. Enter your OpenAI API key in the sidebar if it is not already set as an environment variable or Streamlit secret.
4. In **Workflow**, click **Analyze contract**.
5. Open **Contract** and review the extracted services and pricing rules.
6. Check **I reviewed the contract rules**.
7. Return to **Workflow** and click **Run audit**.
8. Open **Results** to inspect findings, review cases, and invoice details.
9. Download **Contract rules (JSON)** and **Audit results (ZIP)** when needed.

## Reuse contract rules without extracting again

If you previously downloaded a contract-rules JSON file:

1. Open **Advanced settings** in the sidebar.
2. Under **Reuse contract rules**, upload the JSON file.
3. Confirm that the contract rules are ready.
4. Review them in the **Contract** tab.
5. Run the audit.

## OpenAI API key

You can set the key before launching:

```bash
export OPENAI_API_KEY="your-api-key-here"
./run_app.sh
```

If the API has no credit or is temporarily unavailable, the app shows a friendly message. Hospital 1 Validation remains available offline, and previously downloaded contract rules can be uploaded for reuse.

**Do not commit your API key to GitHub.**
