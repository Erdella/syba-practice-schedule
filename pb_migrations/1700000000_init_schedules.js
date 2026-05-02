/// <reference path="../pb_data/types.d.ts" />
//
// Initial migration:
//   - Creates the `schedules` collection (single record holds the entire
//     practice schedule as a JSON blob plus a monotonic version number).
//   - Seeds one record with the league's starter teams and gyms.
//   - Sets API rules: anyone can read; only authenticated users can write.
//
migrate((db) => {
    const collection = new Collection({
        "id": "schedColMain1",
        "name": "schedules",
        "type": "base",
        "system": false,
        "schema": [
            {
                "id": "schDataField",
                "name": "data",
                "type": "json",
                "required": true,
                "options": { "maxSize": 5242880 }
            },
            {
                "id": "schVerField",
                "name": "version",
                "type": "number",
                "required": true,
                "options": { "min": 0, "noDecimal": true }
            }
        ],
        "indexes": [],
        "listRule":   "",                          // public read
        "viewRule":   "",                          // public read
        "createRule": "@request.auth.id != ''",    // login required
        "updateRule": "@request.auth.id != ''",    // login required
        "deleteRule": null                          // admin only
    });

    Dao(db).saveCollection(collection);

    // Seed the single canonical schedule record
    const seed = {
        teams: [
            { id:"t_1", grade:"3rd", gender:"Boys",  name:"Navy",    color:"#0c2340" },
            { id:"t_2", grade:"3rd", gender:"Boys",  name:"Gold",    color:"#c8a93e" },
            { id:"t_3", grade:"3rd", gender:"Girls", name:"Navy",    color:"#0c2340" },
            { id:"t_4", grade:"4th", gender:"Boys",  name:"Navy",    color:"#0369a1" },
            { id:"t_5", grade:"4th", gender:"Girls", name:"Navy",    color:"#be185d" },
            { id:"t_6", grade:"5th", gender:"Boys",  name:"Navy",    color:"#0b6e4f" },
            { id:"t_7", grade:"6th", gender:"Girls", name:"Navy",    color:"#7a3e9d" },
            { id:"t_8", grade:"7th", gender:"Boys",  name:"Varsity", color:"#374151" },
            { id:"t_9", grade:"8th", gender:"Boys",  name:"Varsity", color:"#525252" }
        ],
        gyms: [
            { id:"g_1", name:"Lewis & Clark"    },
            { id:"g_2", name:"Madison"          },
            { id:"g_3", name:"Washington"       },
            { id:"g_4", name:"Discovery MS"     },
            { id:"g_5", name:"Carl Ben Eielson" }
        ],
        practices: [],
        blackouts: []
    };

    const record = new Record(collection, {
        data: seed,
        version: 0
    });
    Dao(db).saveRecord(record);
}, (db) => {
    const dao = new Dao(db);
    const collection = dao.findCollectionByNameOrId("schedules");
    return dao.deleteCollection(collection);
});
