PluginsAPI.Map.willAddControls([
        'annotations/build/Annotations.js',
        'annotations/build/Annotations.css'
    ], function(args, Annotations){
    var tasks = [];
    var ids = {};

    for (var i = 0; i < args.tiles.length; i++){
        var task = args.tiles[i].meta.task;
        if (!ids[task.id]){
            tasks.push(task);
            ids[task.id] = true;
        }
    }

    // Las polilíneas ya guardadas se cargan siempre (FR-030, FR-031); las herramientas de
    // trazado y edición de geometría se restringen a una sola tarea dentro del panel.
    if (tasks.length > 0){
        args.map.addControl(new Annotations({map: args.map, tasks: tasks, tiles: args.tiles}));
    }
});
